from can_transport import CanUdsTransport, DEFAULT_TESTER_ID, DEFAULT_ECU_ID
from uds_common import (
    SID_DIAGNOSTIC_SESSION_CONTROL, SID_SECURITY_ACCESS,
    SID_READ_DATA_BY_IDENTIFIER, SID_WRITE_DATA_BY_IDENTIFIER,
    SID_ROUTINE_CONTROL, SID_TESTER_PRESENT, SID_ECU_RESET,
    NRC_SECURITY_ACCESS_DENIED, UDSError, frame_to_hex
)

class CanTesterClient:
    def __init__(self, channel="uds-can-bus"):
        self.tp = CanUdsTransport(channel, tx_id=DEFAULT_TESTER_ID, rx_id=DEFAULT_ECU_ID)

    def close(self):
        self.tp.close()

    def _send_recv(self, req: bytes) -> bytes:
        print(f"[TESTER] TX: {frame_to_hex(req)}")
        self.tp.send_uds_message(req)
        resp = self.tp.receive_uds_message()
        if resp is None:
            raise RuntimeError("Timeout waiting for response")
        print(f"[TESTER] RX: {frame_to_hex(resp)}")
        if resp[0] == 0x7F:
            nrc = resp[2] if len(resp) > 2 else 0
            raise UDSError(nrc, f"Negative Response: NRC {hex(nrc)}")
        return resp

    def set_session(self, session_type: int):
        resp = self._send_recv(bytes([SID_DIAGNOSTIC_SESSION_CONTROL, session_type]))
        assert resp[0] == SID_DIAGNOSTIC_SESSION_CONTROL + 0x40

    def request_seed(self) -> int:
        resp = self._send_recv(bytes([SID_SECURITY_ACCESS, 0x01]))
        assert resp[0] == SID_SECURITY_ACCESS + 0x40
        return int.from_bytes(resp[2:], byteorder='big')

    def send_key(self, key: int):
        resp = self._send_recv(bytes([SID_SECURITY_ACCESS, 0x02]) + key.to_bytes(2, byteorder='big'))
        assert resp[0] == SID_SECURITY_ACCESS + 0x40

    def read_data_by_identifier(self, did: int) -> int:
        req = bytes([SID_READ_DATA_BY_IDENTIFIER]) + did.to_bytes(2, byteorder='big')
        resp = self._send_recv(req)
        return int.from_bytes(resp[3:], byteorder='big')

    def write_data_by_identifier(self, did: int, val: int):
        req = bytes([SID_WRITE_DATA_BY_IDENTIFIER]) + did.to_bytes(2, byteorder='big') + bytes([val])
        self._send_recv(req)

    def routine_control(self, subfn: int, routine_id: int):
        req = bytes([SID_ROUTINE_CONTROL, subfn]) + routine_id.to_bytes(2, byteorder='big')
        self._send_recv(req)

    def tester_present(self):
        self._send_recv(bytes([SID_TESTER_PRESENT, 0x00]))

    def ecu_reset(self):
        self._send_recv(bytes([SID_ECU_RESET, 0x01]))
