"""
uds_common.py — Shared UDS (ISO 14229) constants.

ELI5: UDS is a request/response language cars use for diagnostics — the
same protocol your mechanic's scan tool speaks to your car's ECU. Every
message starts with a "Service ID" byte that says what you want to do
(start a session, read a value, unlock security, etc).
"""

# ─── Service IDs (what the tester is asking the ECU to do) ─────────────
SID_DIAGNOSTIC_SESSION_CONTROL = 0x10
SID_ECU_RESET                  = 0x11
SID_SECURITY_ACCESS            = 0x27
SID_READ_DATA_BY_IDENTIFIER    = 0x22
SID_WRITE_DATA_BY_IDENTIFIER   = 0x2E
SID_ROUTINE_CONTROL            = 0x31
SID_TESTER_PRESENT             = 0x3E

# A positive response is always (request SID + 0x40). This is a real
# ISO 14229 rule, not something we invented — e.g. a successful 0x10
# (Session Control) request gets back 0x50 as its response SID.
POSITIVE_RESPONSE_OFFSET = 0x40

# Negative response uses a fixed wrapper: [0x7F, original_SID, NRC]
NEGATIVE_RESPONSE_SID = 0x7F

# ─── Negative Response Codes (NRCs) — why a request was rejected ───────
NRC_SERVICE_NOT_SUPPORTED          = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED      = 0x12
NRC_INCORRECT_MESSAGE_LENGTH       = 0x13
NRC_CONDITIONS_NOT_CORRECT         = 0x22
NRC_REQUEST_SEQUENCE_ERROR         = 0x24
NRC_REQUEST_OUT_OF_RANGE           = 0x31
NRC_SECURITY_ACCESS_DENIED         = 0x33
NRC_INVALID_KEY                    = 0x35
NRC_EXCEED_NUMBER_OF_ATTEMPTS      = 0x36
NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED = 0x37

NRC_NAMES = {
    NRC_SERVICE_NOT_SUPPORTED: "serviceNotSupported",
    NRC_SUBFUNCTION_NOT_SUPPORTED: "subFunctionNotSupported",
    NRC_INCORRECT_MESSAGE_LENGTH: "incorrectMessageLengthOrInvalidFormat",
    NRC_CONDITIONS_NOT_CORRECT: "conditionsNotCorrect",
    NRC_REQUEST_SEQUENCE_ERROR: "requestSequenceError",
    NRC_REQUEST_OUT_OF_RANGE: "requestOutOfRange",
    NRC_SECURITY_ACCESS_DENIED: "securityAccessDenied",
    NRC_INVALID_KEY: "invalidKey",
    NRC_EXCEED_NUMBER_OF_ATTEMPTS: "exceedNumberOfAttempts",
    NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED: "requiredTimeDelayNotExpired",
}

# ─── Diagnostic Session types (sub-function of 0x10) ────────────────────
SESSION_DEFAULT   = 0x01
SESSION_PROGRAMMING = 0x02
SESSION_EXTENDED  = 0x03

# ─── A fake but realistic Data Identifier for Read/Write examples ──────
DID_VEHICLE_SPEED = 0xF00D  # made-up DID: "current vehicle speed"

def frame_to_hex(frame: bytes) -> str:
    """Pretty-print a UDS frame the way a bus trace tool would."""
    return " ".join(f"{b:02X}" for b in frame)
