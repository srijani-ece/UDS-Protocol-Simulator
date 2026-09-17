"""
iso_tp.py — ISO-TP (ISO 15765-2) segmentation and reassembly.

ELI5: A CAN frame only holds 8 bytes. A real UDS message (like a
security seed response, or sensor data) is often longer than that.
ISO-TP is the rulebook for splitting a big message into several CAN
frames and putting it back together correctly on the other end —
including handling the case where the receiver needs to say "pause,
I'm not ready for more yet."

Four frame types (this is the actual ISO 15765-2 spec, not something
we invented):

  SINGLE FRAME (SF)       — the whole message fits in one CAN frame
                             (≤ 7 bytes of payload). Simplest case.

  FIRST FRAME (FF)        — message is too big for one frame. This is
                             frame #1: says "here's the TOTAL length,
                             and here's the first 6 bytes."

  CONSECUTIVE FRAME (CF)  — frames #2, #3, #4... each carrying the next
                             7 bytes, numbered 1,2,3...0,1,2... (wraps
                             at 16, since only 4 bits are available for
                             the sequence number) so the receiver can
                             detect a dropped/out-of-order frame.

  FLOW CONTROL (FC)       — sent by the RECEIVER back to the sender,
                             after a First Frame, to say "OK, send me
                             up to N more frames, then wait Xms between
                             batches" (or "STOP, I can't keep up").
                             This is the part most tutorials skip
                             entirely — real ISO-TP is two-directional.
"""

from dataclasses import dataclass, field

# Frame type is stored in the top nibble (4 bits) of the first payload byte
FRAME_TYPE_SF = 0x0  # Single Frame
FRAME_TYPE_FF = 0x1  # First Frame
FRAME_TYPE_CF = 0x2  # Consecutive Frame
FRAME_TYPE_FC = 0x3  # Flow Control

FC_CONTINUE = 0x0   # "send more"
FC_WAIT = 0x1       # "pause, don't send yet"
FC_OVERFLOW = 0x2   # "abort, I can't accept this message"


def build_frames(payload: bytes) -> list[bytes]:
    """
    Splits a UDS payload into a list of 8-byte CAN frame payloads,
    following ISO-TP rules. Does NOT include the Flow Control response
    logic here — that's the receiver's job, handled by IsoTpReceiver.
    """
    length = len(payload)

    # The First Frame length field is only 12 bits (4 bits in byte0's
    # low nibble + all 8 bits of byte1) — so 4095 bytes is the real,
    # architectural ceiling for classical (non-CAN-FD) ISO-TP with
    # normal addressing. Silently truncating a longer payload would
    # make the receiver reconstruct the wrong length — a real
    # correctness bug, not a style nitpick.
    if length > 4095:
        raise ValueError(
            f"Payload of {length} bytes exceeds ISO-TP's 12-bit First "
            f"Frame length limit (4095 bytes for classical CAN, normal "
            f"addressing)."
        )

    if length <= 7:
        # Single Frame: byte0 = [0x0][length in low nibble], then data
        frame = bytes([FRAME_TYPE_SF << 4 | length]) + payload
        frame = frame.ljust(8, b'\x00')  # CAN classic frames are padded to 8 bytes
        return [frame]

    # Multi-frame: First Frame + N Consecutive Frames
    frames = []

    # First Frame: byte0-1 = [0x1][12-bit length], then first 6 data bytes
    ff_byte01 = bytes([
        FRAME_TYPE_FF << 4 | ((length >> 8) & 0x0F),
        length & 0xFF,
    ])
    first_chunk = payload[:6]
    frames.append((ff_byte01 + first_chunk).ljust(8, b'\x00'))

    remaining = payload[6:]
    seq = 1

    while remaining:
        chunk = remaining[:7]
        remaining = remaining[7:]
        cf_byte0 = bytes([FRAME_TYPE_CF << 4 | (seq & 0x0F)])
        frames.append((cf_byte0 + chunk).ljust(8, b'\x00'))
        seq += 1

    return frames


def build_flow_control_frame(
    flow_status: int = FC_CONTINUE,
    block_size: int = 0,
    st_min: int = 0,
) -> bytes:
    """
    Builds the receiver's "go ahead" response.
    block_size: how many Consecutive Frames to send before waiting for
                another Flow Control frame (0 = send all remaining, no limit)
    st_min:     minimum gap (ms) the sender must wait between Consecutive
                Frames — lets a slow receiver control the pace
    """
    frame = bytes([
        FRAME_TYPE_FC << 4 | flow_status,
        block_size,
        st_min,
    ])
    return frame.ljust(8, b'\x00')


@dataclass
class IsoTpReceiver:
    """
    Reassembles a full UDS payload from a stream of incoming CAN
    frames. Feed it frames one at a time via `.receive_frame()`.
    Returns the complete payload once reassembly is done, or None if
    still waiting for more frames.
    """
    _expected_length: int = 0
    _buffer: bytearray = field(default_factory=bytearray)
    _next_seq: int = 1
    _receiving: bool = False

    def receive_frame(self, frame: bytes) -> bytes | None:
        try:
            return self._receive_frame_inner(frame)
        except ValueError:
            # Any protocol error aborts whatever reassembly was in
            # progress. Otherwise a caller that catches the error and
            # keeps feeding frames would corrupt the next message by
            # reassembling into stale leftover state.
            self._receiving = False
            self._buffer = bytearray()
            self._next_seq = 1
            raise

    def _receive_frame_inner(self, frame: bytes) -> bytes | None:
        if not frame:
            raise ValueError("Empty CAN frame passed to ISO-TP receiver")

        if len(frame) < 2:
            raise ValueError(
                f"Malformed ISO-TP frame: only {len(frame)} byte(s), "
                f"need at least 2 (frame-type/length header)"
            )

        frame_type = frame[0] >> 4

        if frame_type == FRAME_TYPE_SF:
            length = frame[0] & 0x0F

            if length == 0:
                raise ValueError("Malformed Single Frame: length field is 0")

            if length > len(frame) - 1:
                raise ValueError(
                    f"Malformed Single Frame: claims {length} bytes of "
                    f"payload but only {len(frame) - 1} bytes present"
                )

            return bytes(frame[1:1 + length])

        elif frame_type == FRAME_TYPE_FF:
            if len(frame) < 8:
                raise ValueError(
                    f"Malformed First Frame: expected 8 bytes, got {len(frame)}"
                )

            self._expected_length = ((frame[0] & 0x0F) << 8) | frame[1]

            if self._expected_length < 8:
                raise ValueError(
                    f"Malformed First Frame: invalid payload length "
                    f"{self._expected_length}"
                )

            # A new First Frame always starts a fresh reassembly, even
            # if one was already in progress (that old one is abandoned).
            self._buffer = bytearray(frame[2:8])
            self._next_seq = 1
            self._receiving = True
            return None

        elif frame_type == FRAME_TYPE_CF:
            if not self._receiving:
                raise ValueError(
                    "Consecutive Frame received with no First Frame in progress"
                )

            seq = frame[0] & 0x0F

            if seq != self._next_seq:
                raise ValueError(
                    f"ISO-TP sequence error: expected CF #{self._next_seq}, got #{seq} "
                    f"(a frame was lost or arrived out of order)"
                )

            remaining_needed = self._expected_length - len(self._buffer)
            self._buffer += frame[1:1 + min(7, remaining_needed)]
            self._next_seq = (self._next_seq + 1) & 0x0F

            if len(self._buffer) >= self._expected_length:
                complete = bytes(self._buffer[:self._expected_length])
                self._receiving = False
                return complete

            return None

        elif frame_type == FRAME_TYPE_FC:
            raise ValueError(
                "Flow Control frame passed to IsoTpReceiver — "
                "this belongs to the SENDER side, not the receiver"
            )

        else:
            raise ValueError(f"Unknown ISO-TP frame type: {frame_type:#x}")