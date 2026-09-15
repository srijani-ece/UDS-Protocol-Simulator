"""
tester_can.py — the same UDSTester API from tester.py, now sending
real requests over CAN + ISO-TP instead of a TCP socket.

Deliberately mirrors UDSTester's exact method names/signatures — a
UDS-writing script shouldn't have to care or even know which
transport is underneath. That's the whole design point of separating
transport from protocol: swap CanUdsTransport for a TCP socket (or
real SocketCAN hardware later) and every test/script that uses this
class doesn't change at all.
"""

import struct

from can_transport import CanUdsTransport, DEFAULT_TESTER_ID, DEFAULT_ECU_ID
from uds_common import (
    SID_DIAGNOSTIC_SESSION_CONTROL, SID_ECU_RESET, SID_SECURITY_ACCESS,
    SID_READ_DATA_BY_IDENTIFIER, SID_WRITE_DATA_BY_IDENTIFIER,
    SID_ROUTINE_CONTROL, SID_TESTER_PRESENT,
    NEGATIVE_RESPONSE_SID, NRC_NAMES, frame_to_hex,
)


class UDSError(Exception):
    def __init__(self, sid, nrc):
        self.sid = sid
        self.nrc = nrc
        name = NRC_NAMES.get(nrc, f"unknown(0x{nrc:02X})")
        super().__init__(f"UDS negative response to SID 0x{sid:02X}: {name} (0x{nrc:02X})")


class UDSTesterCAN:
    def __init__(self, channel: str = "uds-can-bus"):
        self.transport = CanUdsTransport(channel, tx_id=DEFAULT_TESTER_ID, rx_id=DEFAULT_ECU_ID)

    def _transact(self, req: bytes) -> bytes:
        print(f"[Tester-CAN] -> {frame_to_hex(req)}")
        self.transport.send_uds_message(req)
        resp = self.transport.receive_uds_message()
        print(f"[Tester-CAN] <- {frame_to_hex(resp)}")
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
        self.transport.close()