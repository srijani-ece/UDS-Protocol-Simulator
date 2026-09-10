"""
test_uds.py — Proves the simulator actually behaves like a real UDS ECU.
"""

import threading
import time

from uds_common import (
    SID_DIAGNOSTIC_SESSION_CONTROL, SID_SECURITY_ACCESS,
    SID_READ_DATA_BY_IDENTIFIER, SID_WRITE_DATA_BY_IDENTIFIER,
    NEGATIVE_RESPONSE_SID, NRC_SECURITY_ACCESS_DENIED, NRC_INVALID_KEY,
    NRC_SUBFUNCTION_NOT_SUPPORTED, NRC_REQUEST_OUT_OF_RANGE,
    SESSION_EXTENDED, SESSION_DEFAULT, DID_VEHICLE_SPEED,
)
from ecu_simulator import ECUState, handle_request, compute_expected_key, serve
from tester import UDSTester, UDSError


def test_session_control_valid():
    state = ECUState()
    resp = handle_request(state, bytes([SID_DIAGNOSTIC_SESSION_CONTROL, SESSION_EXTENDED]))
    assert resp[0] == SID_DIAGNOSTIC_SESSION_CONTROL + 0x40
    assert state.session == SESSION_EXTENDED
    print("PASS: session control accepts valid session type")


def test_session_control_invalid_subfunction():
    state = ECUState()
    resp = handle_request(state, bytes([SID_DIAGNOSTIC_SESSION_CONTROL, 0x99]))
    assert resp[0] == NEGATIVE_RESPONSE_SID
    assert resp[2] == NRC_SUBFUNCTION_NOT_SUPPORTED
    print("PASS: session control rejects garbage subfunction")


def test_write_without_security_denied():
    state = ECUState()
    state.session = SESSION_EXTENDED
    req = bytes([SID_WRITE_DATA_BY_IDENTIFIER]) + DID_VEHICLE_SPEED.to_bytes(2, "big") + bytes([99])
    resp = handle_request(state, req)
    assert resp[0] == NEGATIVE_RESPONSE_SID
    assert resp[2] == NRC_SECURITY_ACCESS_DENIED
    print("PASS: write correctly denied without security unlock")


def test_security_access_wrong_key_rejected():
    state = ECUState()
    state.session = SESSION_EXTENDED
    seed_resp = handle_request(state, bytes([SID_SECURITY_ACCESS, 0x01]))
    seed = int.from_bytes(seed_resp[2:4], "big")
    wrong_key = (compute_expected_key(seed) ^ 0xFFFF) & 0xFFFF
    resp = handle_request(state, bytes([SID_SECURITY_ACCESS, 0x02]) + wrong_key.to_bytes(2, "big"))
    assert resp[0] == NEGATIVE_RESPONSE_SID
    assert resp[2] == NRC_INVALID_KEY
    assert state.security_unlocked is False
    print("PASS: wrong security key correctly rejected, ECU stays locked")


def test_security_access_correct_key_unlocks():
    state = ECUState()
    state.session = SESSION_EXTENDED
    seed_resp = handle_request(state, bytes([SID_SECURITY_ACCESS, 0x01]))
    seed = int.from_bytes(seed_resp[2:4], "big")
    correct_key = compute_expected_key(seed)
    resp = handle_request(state, bytes([SID_SECURITY_ACCESS, 0x02]) + correct_key.to_bytes(2, "big"))
    assert resp[0] == SID_SECURITY_ACCESS + 0x40
    assert state.security_unlocked is True
    print("PASS: correct security key unlocks the ECU")


def test_read_unsupported_did_out_of_range():
    state = ECUState()
    resp = handle_request(state, bytes([SID_READ_DATA_BY_IDENTIFIER, 0x99, 0x99]))
    assert resp[0] == NEGATIVE_RESPONSE_SID
    assert resp[2] == NRC_REQUEST_OUT_OF_RANGE
    print("PASS: reading an unknown DID correctly rejected")


def test_end_to_end_full_session():
    server_thread = threading.Thread(target=serve, kwargs={"port": 13401}, daemon=True)
    server_thread.start()
    time.sleep(0.3)

    t = UDSTester(port=13401)

    t.diagnostic_session_control(SESSION_EXTENDED)

    original_speed = t.read_data_by_identifier(DID_VEHICLE_SPEED)
    assert original_speed == 42

    try:
        t.write_data_by_identifier(DID_VEHICLE_SPEED, 100)
        assert False, "write should have been rejected before security unlock"
    except UDSError as e:
        assert e.nrc == NRC_SECURITY_ACCESS_DENIED

    seed = t.request_seed()
    key = compute_expected_key(seed)
    t.send_key(key)

    t.write_data_by_identifier(DID_VEHICLE_SPEED, 100)
    new_speed = t.read_data_by_identifier(DID_VEHICLE_SPEED)
    assert new_speed == 100

    t.routine_control(subfn=0x01, routine_id=0x0203)
    t.tester_present()
    t.ecu_reset()

    t.close()
    print("PASS: full end-to-end diagnostic session completed correctly")


if __name__ == "__main__":
    test_session_control_valid()
    test_session_control_invalid_subfunction()
    test_write_without_security_denied()
    test_security_access_wrong_key_rejected()
    test_security_access_correct_key_unlocks()
    test_read_unsupported_did_out_of_range()
    test_end_to_end_full_session()
    print("\nALL TESTS PASSED")
