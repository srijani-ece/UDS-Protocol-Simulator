import time

SID_DIAGNOSTIC_SESSION_CONTROL = 0x10
SID_SECURITY_ACCESS            = 0x27
SID_READ_DATA_BY_IDENTIFIER    = 0x22
SID_WRITE_DATA_BY_IDENTIFIER   = 0x2E
SID_ROUTINE_CONTROL            = 0x31
SID_TESTER_PRESENT             = 0x3E
SID_ECU_RESET                  = 0x11

NRC_SERVICE_NOT_SUPPORTED      = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED  = 0x12
NRC_INCORRECT_MESSAGE_LENGTH   = 0x13
NRC_CONDITIONS_NOT_CORRECT     = 0x22
NRC_REQUEST_OUT_OF_RANGE       = 0x31
NRC_SECURITY_ACCESS_DENIED     = 0x33
NRC_INVALID_KEY                = 0x35

DID_VEHICLE_SPEED = 0x0100
DID_ENGINE_RPM    = 0x0101

class UDSError(Exception):
    def __init__(self, nrc: int, message: str = ""):
        self.nrc = nrc
        super().__init__(message or f"NRC {hex(nrc)}")

class ECUState:
    def __init__(self):
        self.session = 0x01  # Default Session
        self.security_unlocked = False
        self.seed = 0x1234
        self.dids = {
            DID_VEHICLE_SPEED: 0,
            DID_ENGINE_RPM: 800
        }

def compute_expected_key(seed: int) -> int:
    return (seed ^ 0xDEAD) & 0xFFFF

def frame_to_hex(frame: bytes) -> str:
    return ' '.join(f"{b:02X}" for b in frame)

def handle_request(state: ECUState, req: bytes) -> bytes:
    if not req:
        return bytes([0x7F, 0x00, NRC_INCORRECT_MESSAGE_LENGTH])

    sid = req[0]

    if sid == SID_DIAGNOSTIC_SESSION_CONTROL:
        if len(req) < 2:
            return bytes([0x7F, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        session_type = req[1]
        state.session = session_type
        state.security_unlocked = False
        return bytes([0x50, session_type, 0x00, 0x32, 0x01, 0xF4])

    elif sid == SID_SECURITY_ACCESS:
        if len(req) < 2:
            return bytes([0x7F, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        subfn = req[1]
        if subfn == 0x01:
            state.seed = int(time.time()) & 0xFFFF
            if state.seed == 0:
                state.seed = 0x1234
            seed_bytes = state.seed.to_bytes(2, byteorder='big')
            return bytes([0x67, 0x01]) + seed_bytes
        elif subfn == 0x02:
            if len(req) < 4:
                return bytes([0x7F, sid, NRC_INCORRECT_MESSAGE_LENGTH])
            provided_key = int.from_bytes(req[2:4], byteorder='big')
            if provided_key == compute_expected_key(state.seed):
                state.security_unlocked = True
                return bytes([0x67, 0x02])
            else:
                return bytes([0x7F, sid, NRC_INVALID_KEY])
        return bytes([0x7F, sid, NRC_SUBFUNCTION_NOT_SUPPORTED])

    elif sid == SID_READ_DATA_BY_IDENTIFIER:
        if len(req) < 3:
            return bytes([0x7F, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        did = int.from_bytes(req[1:3], byteorder='big')
        if did in state.dids:
            val = state.dids[did]
            val_bytes = val.to_bytes(1 if val < 256 else 2, byteorder='big')
            return bytes([0x62]) + req[1:3] + val_bytes
        return bytes([0x7F, sid, NRC_REQUEST_OUT_OF_RANGE])

    elif sid == SID_WRITE_DATA_BY_IDENTIFIER:
        if not state.security_unlocked:
            return bytes([0x7F, sid, NRC_SECURITY_ACCESS_DENIED])
        if len(req) < 4:
            return bytes([0x7F, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        did = int.from_bytes(req[1:3], byteorder='big')
        val = req[3]
        state.dids[did] = val
        return bytes([0x6E]) + req[1:3]

    elif sid == SID_ROUTINE_CONTROL:
        if len(req) < 4:
            return bytes([0x7F, sid, NRC_INCORRECT_MESSAGE_LENGTH])
        return bytes([0x71, req[1]]) + req[2:4]

    elif sid == SID_TESTER_PRESENT:
        return bytes([0x7E, req[1] if len(req) > 1 else 0x00])

    elif sid == SID_ECU_RESET:
        state.session = 0x01
        state.security_unlocked = False
        return bytes([0x51, req[1] if len(req) > 1 else 0x01])

    return bytes([0x7F, sid, NRC_SERVICE_NOT_SUPPORTED])
