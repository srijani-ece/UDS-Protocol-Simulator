"""
test_uds_over_can.py — the same full diagnostic session as
test_end_to_end_full_session() in test_uds.py, but this time running
over the real CAN + ISO-TP transport instead of TCP. This is the
actual proof that the transport swap works — not just that ISO-TP
framing works in isolation (already proven in test_can_transport.py),
but that the FULL UDS protocol stack (session control, security
access, RDBI/WDBI, routine control, reset) behaves identically when
the plumbing underneath is completely different.

Honest note: every individual message in THIS particular session is
short enough to fit in a Single Frame (the seed/key response, DID
reads, etc. are all a handful of bytes) — real UDS traffic is often
this small. Multi-frame segmentation across several CAN frames is
proven separately, with a deliberately larger synthetic payload, in
test_can_transport.py. This test's job is proving the PROTOCOL logic
survives the transport swap unchanged — not re-proving segmentation.
"""

import threading
import time

from ecu_can import run_can_ecu as serve_can
from tester_can import UDSTesterCAN, UDSError
from ecu_simulator import compute_expected_key
from uds_common import SESSION_EXTENDED, DID_VEHICLE_SPEED, NRC_SECURITY_ACCESS_DENIED


def test_full_session_over_can():
    channel = "test-integration-channel"

    server_thread = threading.Thread(
        target=serve_can,
        kwargs={"channel": channel},
        daemon=True
    )
    server_thread.start()
    time.sleep(0.5)   # bumped from 0.3 — still a guess, not a real signal (see note below)

    t = UDSTesterCAN(channel=channel)
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
    print(
        "PASS: full UDS diagnostic session (session control, security access, "
        "RDBI/WDBI, routine control, reset) completed correctly over real CAN + ISO-TP transport"
    )


if __name__ == "__main__":
    test_full_session_over_can()
    print("\nALL CAN INTEGRATION TESTS PASSED")