"""
can_transport.py — sends and receives full UDS messages over a real
CAN bus interface (via python-can), automatically handling ISO-TP
segmentation/reassembly underneath so the UDS layer above never has
to think about 8-byte frame limits.

Uses python-can's 'virtual' backend — a real in-process CAN bus with
no kernel driver dependency, so this runs anywhere (no root, no
SocketCAN/vcan0 setup needed). Swapping to real hardware later is a
ONE-LINE change (bustype='socketcan', channel='vcan0' or 'can0') —
everything above this line (ISO-TP, UDS logic) doesn't change at all,
which is exactly the point of layering transport separately from
protocol logic.
"""

import can
import time

from iso_tp import (
    build_frames, build_flow_control_frame, IsoTpReceiver,
    FRAME_TYPE_FC, FC_CONTINUE, FC_WAIT,
)

DEFAULT_TESTER_ID = 0x7E0  # standard-ish diagnostic request arbitration ID
DEFAULT_ECU_ID    = 0x7E8  # standard-ish diagnostic response arbitration ID
MAX_FC_WAIT_FRAMES = 3

class CanUdsTransport:
    """
    One instance per 'side' of the conversation (tester or ECU).
    Both sides connect to the SAME virtual channel name to share a bus,
    exactly like two real ECUs wired to the same physical CAN bus.
    """

    def __init__(self, channel: str, tx_id: int, rx_id: int, timeout: float = 2.0):
        self.bus = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.timeout = timeout

    def send_uds_message(self, payload: bytes):
        """
        Sends a full UDS message, transparently splitting it into
        multiple CAN frames via ISO-TP if it doesn't fit in one.
        """
        frames = build_frames(payload)

        if len(frames) == 1:
            self._send_can_frame(frames[0])
            return

        # Multi-frame: send First Frame, then WAIT for the receiver's
        # Flow Control response before sending ANY Consecutive Frames.
        self._send_can_frame(frames[0])

        consecutive_frames = frames[1:]
        sent = 0
        fc_wait_count = 0

        # Real ISO-TP Flow Control governs pacing with TWO numbers, not
        # one: Block Size (how many CFs to send before requiring another
        # FC) and STmin (minimum gap between individual CFs). A receiver
        # can legitimately say "send me 8, then check in with me again"
        # — ignoring Block Size and blasting every CF after a single FC
        # defeats the actual purpose of flow control (letting a slow
        # receiver throttle a fast sender).
        while sent < len(consecutive_frames):
            fc = self._receive_can_frame()
            if fc is None or (fc[0] >> 4) != FRAME_TYPE_FC:
                raise TimeoutError("Expected Flow Control frame, got none or wrong type")

            flow_status = fc[0] & 0x0F
            block_size = fc[1]
            st_min_seconds = self._decode_st_min(fc[2])

            if flow_status == FC_WAIT:
                fc_wait_count += 1

                if fc_wait_count > MAX_FC_WAIT_FRAMES:
                    raise TimeoutError(
                        f"Receiver sent too many consecutive Flow Control WAIT "
                        f"frames ({fc_wait_count})"
                    )

                # Receiver isn't ready yet - wait for another FC.
                continue
            if flow_status != FC_CONTINUE:
                raise RuntimeError(
                    f"Receiver aborted the transfer (Flow Control status "
                    f"{flow_status:#x}, e.g. OVERFLOW)"
                )
            fc_wait_count = 0

            # block_size == 0 means "no limit, send everything remaining"
            batch_size = len(consecutive_frames) - sent if block_size == 0 else block_size

            for cf in consecutive_frames[sent:sent + batch_size]:
                self._send_can_frame(cf)
                if st_min_seconds > 0:
                    time.sleep(st_min_seconds)
            sent += batch_size

    @staticmethod
    def _decode_st_min(raw: int) -> float:
        """
        ISO-TP's STmin byte isn't a single linear scale — it's two
        separate encoded ranges sharing one byte:
          0x00-0x7F -> 0-127 milliseconds, directly
          0xF1-0xF9 -> 100-900 MICROseconds (sub-millisecond timing)
          0x80-0xF0 and 0xFA-0xFF -> reserved/invalid by spec

        Treating the whole byte as "milliseconds" (a common shortcut in
        simplified ISO-TP examples) silently misinterprets any
        sub-millisecond request by roughly 1000x.
        """
        if 0x00 <= raw <= 0x7F:
            return raw / 1000.0
        elif 0xF1 <= raw <= 0xF9:
            microseconds = (raw - 0xF0) * 100
            return microseconds / 1_000_000.0
        else:
            raise ValueError(
                f"Invalid/reserved ISO-TP STmin value: {raw:#04x}"
            )

    def receive_uds_message(self, fc_block_size: int = 0, fc_st_min: int = 0) -> bytes:
        """
        Receives a full UDS message, automatically sending a Flow
        Control frame if the incoming message turns out to be
        multi-frame, and reassembling all Consecutive Frames.

        fc_block_size / fc_st_min let a caller simulate a genuinely
        resource-constrained receiver (default 0/0 = "send everything,
        no pacing needed" — fine for this simulation's ECU, but real
        hardware often isn't that generous).
        """
        receiver = IsoTpReceiver()

        while True:
            frame = self._receive_can_frame()
            if frame is None:
                raise TimeoutError("No CAN frame received within timeout")

            result = receiver.receive_frame(frame)

            if (frame[0] >> 4) == 0x1:  # just processed a First Frame
                self._send_can_frame(
                    build_flow_control_frame(FC_CONTINUE, fc_block_size, fc_st_min)
                )

            if result is not None:
                return result
            elif (frame[0] >> 4) == 0x2 and fc_block_size > 0:
                # Just consumed one Consecutive Frame and a real block
                # size is in effect — track how many CFs we've allowed
                # through this block, and issue another Flow Control
                # once the block is exhausted.
                self._cf_count_in_block = getattr(self, "_cf_count_in_block", 0) + 1
                if self._cf_count_in_block >= fc_block_size:
                    self._cf_count_in_block = 0
                    self._send_can_frame(
                        build_flow_control_frame(FC_CONTINUE, fc_block_size, fc_st_min)
                    )

    def _send_can_frame(self, data: bytes):
        msg = can.Message(arbitration_id=self.tx_id, data=data, is_extended_id=False)
        self.bus.send(msg)

    def _receive_can_frame(self) -> bytes | None:
        # On a real shared CAN bus, other nodes' traffic arrives
        # interleaved with ours. Treating the FIRST frame that doesn't
        # match our expected ID as "nothing arrived" is wrong — it
        # should be ignored, not mistaken for a timeout, as long as we
        # still have time left to wait for the real one.
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            msg = self.bus.recv(timeout=remaining)
            if msg is None:
                return None
            if msg.arbitration_id == self.rx_id:
                return bytes(msg.data)
            # else: not our frame — loop again with whatever time's left

    def close(self):
        self.bus.shutdown()