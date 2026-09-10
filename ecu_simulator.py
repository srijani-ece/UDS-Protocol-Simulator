"""
ecu_simulator.py — The "car" side. Listens for UDS requests over a TCP
socket (standing in for the real bus) and responds like a real ECU would.
"""

import socket
import struct
import random

from uds_common import (
    SID_DIAGNOSTIC_SESSION_CONTROL, SID_ECU_RESET, SID_SECURITY_ACCESS,
    SID_READ_DATA_BY_IDENTIFIER, SID_WRITE_DATA_BY_IDENTIFIER,
    SID_ROUTINE_CONTROL, SID_TESTER_PRESENT,
    POSITIVE_RESPONSE_OFFSET, NEGATIVE_RESPONSE_SID,
    NRC_SERVICE_NOT_SUPPORTED, NRC_SUBFUNCTION_NOT_SUPPORTED,
    NRC_INCORRECT_MESSAGE_LENGTH, NRC_CONDITIONS_NOT_CORRECT,
    NRC_REQUEST_OUT_OF_RANGE, NRC_SECURITY_ACCESS_DENIED, NRC_INVALID_KEY,
    SESSION_DEFAULT, SESSION_PROGRAMMING, SESSION_EXTENDED,
    DID_VEHICLE_SPEED, frame_to_hex,
)


class ECUState:
    def __init__(self):
        self.session = SESSION_DEFAULT
        self.security_unlocked = False
        self.pending_seed = None
        self.vehicle_speed_kph = 42


def compute_expected_key(seed: int) -> int:
    return (seed ^ 0xA5A5) & 0xFFFF


def handle_request(state: ECUState, req: bytes) -> bytes:
    if len(req) < 1:
        return bytes([NEGATIVE_RESPONSE_SID, 0x00, NRC_INCORRECT_MESSAGE_LENGTH])

    sid = req[0]

    if sid == SID_DIAGNOSTIC_SESSION_CONTROL:
        if len(req) != 2:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        subfn = req[1]
        if subfn not in (SESSION_DEFAULT, SESSION_PROGRAMMING, SESSION_EXTENDED):
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_SUBFUNCTION_NOT_SUPPORTED])
        state.session = subfn
        state.security_unlocked = False
        return bytes([sid + POSITIVE_RESPONSE_OFFSET, subfn])

    elif sid == SID_TESTER_PRESENT:
        return bytes([sid + POSITIVE_RESPONSE_OFFSET, 0x00])

    elif sid == SID_SECURITY_ACCESS:
        if len(req) < 2:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        subfn = req[1]

        if state.session == SESSION_DEFAULT:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_CONDITIONS_NOT_CORRECT])

        if subfn == 0x01:
            seed = random.randint(0, 0xFFFF)
            state.pending_seed = seed
            return bytes([sid + POSITIVE_RESPONSE_OFFSET, 0x01]) + struct.pack(">H", seed)

        elif subfn == 0x02:
            if state.pending_seed is None or len(req) != 4:
                return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_REQUEST_OUT_OF_RANGE])
            key = struct.unpack(">H", req[2:4])[0]
            expected = compute_expected_key(state.pending_seed)
            state.pending_seed = None
            if key == expected:
                state.security_unlocked = True
                return bytes([sid + POSITIVE_RESPONSE_OFFSET, 0x02])
            else:
                return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_INVALID_KEY])
        else:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_SUBFUNCTION_NOT_SUPPORTED])

    elif sid == SID_READ_DATA_BY_IDENTIFIER:
        if len(req) != 3:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        did = struct.unpack(">H", req[1:3])[0]
        if did != DID_VEHICLE_SPEED:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_REQUEST_OUT_OF_RANGE])
        return bytes([sid + POSITIVE_RESPONSE_OFFSET]) + struct.pack(">H", did) + bytes([state.vehicle_speed_kph])

    elif sid == SID_WRITE_DATA_BY_IDENTIFIER:
        if len(req) != 4:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        if not state.security_unlocked:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_SECURITY_ACCESS_DENIED])
        did = struct.unpack(">H", req[1:3])[0]
        if did != DID_VEHICLE_SPEED:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_REQUEST_OUT_OF_RANGE])
        state.vehicle_speed_kph = req[3]
        return bytes([sid + POSITIVE_RESPONSE_OFFSET]) + struct.pack(">H", did)

    elif sid == SID_ROUTINE_CONTROL:
        if len(req) != 4:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        if not state.security_unlocked:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_SECURITY_ACCESS_DENIED])
        subfn = req[1]
        routine_id = struct.unpack(">H", req[2:4])[0]
        return bytes([sid + POSITIVE_RESPONSE_OFFSET, subfn]) + struct.pack(">H", routine_id)

    elif sid == SID_ECU_RESET:
        if len(req) != 2:
            return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        state.session = SESSION_DEFAULT
        state.security_unlocked = False
        return bytes([sid + POSITIVE_RESPONSE_OFFSET, req[1]])

    else:
        return bytes([NEGATIVE_RESPONSE_SID, sid, NRC_SERVICE_NOT_SUPPORTED])


def serve(host="127.0.0.1", port=13400):
    state = ECUState()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        print(f"[ECU] listening on {host}:{port}")
        conn, addr = srv.accept()
        with conn:
            print(f"[ECU] tester connected from {addr}")
            while True:
                req = conn.recv(256)
                if not req:
                    break
                print(f"[ECU] <- {frame_to_hex(req)}")
                resp = handle_request(state, req)
                print(f"[ECU] -> {frame_to_hex(resp)}")
                conn.sendall(resp)


if __name__ == "__main__":
    serve()
