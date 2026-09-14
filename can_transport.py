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
    FRAME_TYPE_FC, FC_CONTINUE,
)

DEFAULT_TESTER_ID = 0x7E0  # standard-ish diagnostic request arbitration ID
DEFAULT_ECU_ID    = 0x7E8  # standard-ish diagnostic response arbitration ID


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
        # Flow Control response before sending the Consecutive Frames —
        # this is the real two-directional handshake most simplified
        # ISO-TP examples skip entirely.
        self._send_can_frame(frames[0])

        fc = self._receive_can_frame()
        if fc is None or (fc[0] >> 4) != FRAME_TYPE_FC:
            raise TimeoutError("Expected Flow Control frame, got none or wrong type")
        flow_status = fc[0] & 0x0F
        st_min_ms = fc[2]
        if flow_status != FC_CONTINUE:
            raise RuntimeError(f"Receiver signaled non-continue Flow Control status: {flow_status}")

        for cf in frames[1:]:
            self._send_can_frame(cf)
            if st_min_ms > 0:
                time.sleep(st_min_ms / 1000.0)

    def receive_uds_message(self) -> bytes:
        """
        Receives a full UDS message, automatically sending a Flow
        Control frame if the incoming message turns out to be
        multi-frame, and reassembling all Consecutive Frames.
        """
        receiver = IsoTpReceiver()

        while True:
            frame = self._receive_can_frame()
            if frame is None:
                raise TimeoutError("No CAN frame received within timeout")

            result = receiver.receive_frame(frame)

            if (frame[0] >> 4) == 0x1:  # just processed a First Frame
                # Tell the sender to go ahead: block_size=0 (no limit),
                # st_min=0 (no minimum delay needed) — we're not a
                # resource-constrained receiver in this simulation.
                self._send_can_frame(build_flow_control_frame(FC_CONTINUE, 0, 0))

            if result is not None:
                return result

    def _send_can_frame(self, data: bytes):
        msg = can.Message(arbitration_id=self.tx_id, data=data, is_extended_id=False)
        self.bus.send(msg)

    def _receive_can_frame(self) -> bytes | None:
        msg = self.bus.recv(timeout=self.timeout)
        if msg is None or msg.arbitration_id != self.rx_id:
            return None
        return bytes(msg.data)

    def close(self):
        self.bus.shutdown()
