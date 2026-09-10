"""
tester.py — The "diagnostic tool" side.
"""

import socket
import struct

from uds_common import (
    SID_DIAGNOSTIC_SESSION_CONTROL, SID_ECU_RESET, SID_SECURITY_ACCESS,
    SID_READ_DATA_BY_IDENTIFIER, SID_WRITE_DATA_BY_IDENTIFIER,
    SID_ROUTINE_CONTROL, SID_TESTER_PRESENT,
    NEGATIVE_RESPONSE_SID, NRC_NAMES,
    SESSION_EXTENDED, DID_VEHICLE_SPEED, frame_to_hex,
)


class UDSError(Exception):
    def __init__(self, sid, nrc):
        self.sid = sid
        self.nrc = nrc
        name = NRC_NAMES.get(nrc, f"unknown(0x{nrc:02X})")
        super().__init__(f"UDS negative response to SID 0x{sid:02X}: {name} (0x{nrc:02X})")


class UDSTester:
    def __init__(self, host="127.0.0.1", port=13400):
        self.sock = socket.create_connection((host, port))

    def _transact(self, req: bytes) -> bytes:
        print(f"[Tester] -> {frame_to_hex(req)}")
        self.sock.sendall(req)
        resp = self.sock.recv(256)
        print(f"[Tester] <- {frame_to_hex(resp)}")
        if resp[0] == NEGATIVE_RESPONSE_SID:
            raise UDSError(resp[1], resp[2])
        return resp

    def diagnostic_session_control(self, session: int) -> bytes:
        return self._transact(bytes([SID_DIAGNOSTIC_SESSION_CONTROL, session]))

    def tester_present(self) -> bytes:
        return self._transact(bytes([SID_TESTER_PRESENT, 0x00]))

    def request_seed(self) -> int:
        resp = self._transact(bytes([SID_SECURITY_ACCESS, 0x01]))
        return struct.unpack(">H", resp[2:4])[0]

    def send_key(self, key: int) -> bytes:
        return self._transact(bytes([SID_SECURITY_ACCESS, 0x02]) + struct.pack(">H", key))

    def read_data_by_identifier(self, did: int) -> int:
        resp = self._transact(bytes([SID_READ_DATA_BY_IDENTIFIER]) + struct.pack(">H", did))
        return resp[3]

    def write_data_by_identifier(self, did: int, value: int) -> bytes:
        return self._transact(
            bytes([SID_WRITE_DATA_BY_IDENTIFIER]) + struct.pack(">H", did) + bytes([value])
        )

    def routine_control(self, subfn: int, routine_id: int) -> bytes:
        return self._transact(
            bytes([SID_ROUTINE_CONTROL, subfn]) + struct.pack(">H", routine_id)
        )

    def ecu_reset(self, reset_type: int = 0x01) -> bytes:
        return self._transact(bytes([SID_ECU_RESET, reset_type]))

    def close(self):
        self.sock.close()
