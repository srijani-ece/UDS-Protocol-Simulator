"""
ecu_simulator.py — The "car" side. Listens for UDS requests over a TCP
socket (standing in for the real bus) and responds like a real ECU would.
"""

import socket
import struct
import secrets
import time

from uds_common import (
    SID_DIAGNOSTIC_SESSION_CONTROL,
    SID_ECU_RESET,
    SID_SECURITY_ACCESS,
    SID_READ_DATA_BY_IDENTIFIER,
    SID_WRITE_DATA_BY_IDENTIFIER,
    SID_ROUTINE_CONTROL,
    SID_TESTER_PRESENT,
    POSITIVE_RESPONSE_OFFSET,
    NEGATIVE_RESPONSE_SID,
    NRC_SERVICE_NOT_SUPPORTED,
    NRC_SUBFUNCTION_NOT_SUPPORTED,
    NRC_INCORRECT_MESSAGE_LENGTH,
    NRC_CONDITIONS_NOT_CORRECT,
    NRC_REQUEST_SEQUENCE_ERROR,
    NRC_REQUEST_OUT_OF_RANGE,
    NRC_SECURITY_ACCESS_DENIED,
    NRC_INVALID_KEY,
    NRC_EXCEED_NUMBER_OF_ATTEMPTS,
    NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED,
    SESSION_DEFAULT,
    SESSION_PROGRAMMING,
    SESSION_EXTENDED,
    DID_VEHICLE_SPEED,
    frame_to_hex,
)

MAX_KEY_ATTEMPTS = 3
LOCKOUT_SECONDS = 10.0
S3_TIMEOUT_SECONDS = 5.0


class ECUState:
    def __init__(self):
        self.session = SESSION_DEFAULT
        self.security_unlocked = False
        self.pending_seed = None
        self.vehicle_speed_kph = 42
        self.failed_key_attempts = 0
        self.locked_until = 0.0   # monotonic timestamp; 0 = not locked
        self.last_activity = time.monotonic()


def compute_expected_key(seed: int) -> int:
    return (seed ^ 0xA5A5) & 0xFFFF


def handle_request(state: ECUState, req: bytes) -> bytes:
    # S3 server timer: if the tester goes quiet for too long in a
    # non-default session, the ECU drops back to default session and
    # relocks security — this is what makes TesterPresent (0x3E)
    # actually matter instead of being a no-op stub.
    now = time.monotonic()

    if (
        state.session != SESSION_DEFAULT
        and (now - state.last_activity) > S3_TIMEOUT_SECONDS
    ):
        state.session = SESSION_DEFAULT
        state.security_unlocked = False

    state.last_activity = now

    if len(req) < 1:
        return bytes(
            [NEGATIVE_RESPONSE_SID, 0x00, NRC_INCORRECT_MESSAGE_LENGTH]
        )

    sid = req[0]

    if sid == SID_DIAGNOSTIC_SESSION_CONTROL:
        if len(req) != 2:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH]
            )

        suppress = bool(req[1] & 0x80)
        subfn = req[1] & 0x7F

        if subfn not in (
            SESSION_DEFAULT,
            SESSION_PROGRAMMING,
            SESSION_EXTENDED,
        ):
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_SUBFUNCTION_NOT_SUPPORTED]
            )

        state.session = subfn
        state.security_unlocked = False

        if suppress:
            return b""   # caller sends nothing back

        return bytes([sid + POSITIVE_RESPONSE_OFFSET, subfn])

    elif sid == SID_TESTER_PRESENT:
        if len(req) != 2:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH]
            )

        suppress = bool(req[1] & 0x80)
        subfn = req[1] & 0x7F

        if subfn != 0x00:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_SUBFUNCTION_NOT_SUPPORTED]
            )

        if suppress:
            return b""

        return bytes([sid + POSITIVE_RESPONSE_OFFSET, 0x00])

    elif sid == SID_SECURITY_ACCESS:
        if len(req) < 2:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH]
            )

        subfn = req[1]

        if state.session == SESSION_DEFAULT:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_CONDITIONS_NOT_CORRECT]
            )

        # Locked out from too many bad keys? Refuse both seed and key
        # requests until the lockout timer expires.
        if time.monotonic() < state.locked_until:
            return bytes(
                [
                    NEGATIVE_RESPONSE_SID,
                    sid,
                    NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED,
                ]
            )

        if subfn == 0x01:
            if state.security_unlocked:
                # Spec behavior: if already unlocked, hand back a seed
                # of all-zeroes instead of a fresh live seed.
                state.pending_seed = None
                return (
                    bytes([sid + POSITIVE_RESPONSE_OFFSET, 0x01])
                    + struct.pack(">H", 0)
                )

            # secrets (not random) — even in a simulator, using the
            # module actually intended for security-relevant values is
            # the correct habit, and avoids any predictability concern
            # in the seed.
            seed = secrets.randbelow(0x10000)
            state.pending_seed = seed

            return (
                bytes([sid + POSITIVE_RESPONSE_OFFSET, 0x01])
                + struct.pack(">H", seed)
            )

        elif subfn == 0x02:
            if len(req) != 4:
                return bytes(
                    [
                        NEGATIVE_RESPONSE_SID,
                        sid,
                        NRC_INCORRECT_MESSAGE_LENGTH,
                    ]
                )

            if state.pending_seed is None:
                # Real UDS distinguishes "wrong length" from "you sent a
                # key without ever requesting a seed first" — the latter
                # is a request-SEQUENCE error (0x24), not an out-of-range
                # value. Precise NRC choice matters: a real diagnostic
                # tool branches its retry logic differently per NRC.
                return bytes(
                    [
                        NEGATIVE_RESPONSE_SID,
                        sid,
                        NRC_REQUEST_SEQUENCE_ERROR,
                    ]
                )

            key = struct.unpack(">H", req[2:4])[0]
            expected = compute_expected_key(state.pending_seed)
            state.pending_seed = None

            if key == expected:
                state.security_unlocked = True
                state.failed_key_attempts = 0

                return bytes([sid + POSITIVE_RESPONSE_OFFSET, 0x02])

            else:
                state.failed_key_attempts += 1

                if state.failed_key_attempts >= MAX_KEY_ATTEMPTS:
                    state.locked_until = (
                        time.monotonic() + LOCKOUT_SECONDS
                    )
                    state.failed_key_attempts = 0

                    return bytes(
                        [
                            NEGATIVE_RESPONSE_SID,
                            sid,
                            NRC_EXCEED_NUMBER_OF_ATTEMPTS,
                        ]
                    )

                return bytes(
                    [NEGATIVE_RESPONSE_SID, sid, NRC_INVALID_KEY]
                )

        else:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_SUBFUNCTION_NOT_SUPPORTED]
            )

    elif sid == SID_READ_DATA_BY_IDENTIFIER:
        if len(req) != 3:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH]
            )

        did = struct.unpack(">H", req[1:3])[0]

        if did != DID_VEHICLE_SPEED:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_REQUEST_OUT_OF_RANGE]
            )

        return (
            bytes([sid + POSITIVE_RESPONSE_OFFSET])
            + struct.pack(">H", did)
            + bytes([state.vehicle_speed_kph])
        )

    elif sid == SID_WRITE_DATA_BY_IDENTIFIER:
        if len(req) != 4:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH]
            )

        if not state.security_unlocked:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_SECURITY_ACCESS_DENIED]
            )

        did = struct.unpack(">H", req[1:3])[0]

        if did != DID_VEHICLE_SPEED:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_REQUEST_OUT_OF_RANGE]
            )

        state.vehicle_speed_kph = req[3]

        return (
            bytes([sid + POSITIVE_RESPONSE_OFFSET])
            + struct.pack(">H", did)
        )

    elif sid == SID_ROUTINE_CONTROL:
        if len(req) != 4:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH]
            )

        if not state.security_unlocked:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_SECURITY_ACCESS_DENIED]
            )

        suppress = bool(req[1] & 0x80)
        subfn = req[1] & 0x7F
        routine_id = struct.unpack(">H", req[2:4])[0]

        if suppress:
            return b""

        return (
            bytes([sid + POSITIVE_RESPONSE_OFFSET, subfn])
            + struct.pack(">H", routine_id)
        )

    elif sid == SID_ECU_RESET:
        if len(req) != 2:
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_INCORRECT_MESSAGE_LENGTH]
            )

        reset_type = req[1]

        if reset_type not in (0x01, 0x02, 0x03, 0x04, 0x05):
            return bytes(
                [NEGATIVE_RESPONSE_SID, sid, NRC_SUBFUNCTION_NOT_SUPPORTED]
            )

        state.session = SESSION_DEFAULT
        state.security_unlocked = False
        state.failed_key_attempts = 0
        state.locked_until = 0.0
        state.pending_seed = None

        return bytes([sid + POSITIVE_RESPONSE_OFFSET, reset_type])

    else:
        return bytes(
            [NEGATIVE_RESPONSE_SID, sid, NRC_SERVICE_NOT_SUPPORTED]
        )


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

                try:
                    resp = handle_request(state, req)

                except Exception as e:
                    print(f"[ECU] !! error handling request: {e}")
                    continue

                if not resp:
                    # suppressPosRspMsgIndicationBit was set — send nothing.
                    print(f"[ECU] (response suppressed by tester)")
                    continue

                print(f"[ECU] -> {frame_to_hex(resp)}")
                conn.sendall(resp)


if __name__ == "__main__":
    serve()