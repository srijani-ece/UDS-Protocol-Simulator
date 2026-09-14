import threading
import time
from ecu_can import run_can_ecu
from tester_can import CanTesterClient
from uds_common import compute_expected_key, DID_VEHICLE_SPEED, NRC_SECURITY_ACCESS_DENIED, UDSError

def test_full_session_over_can():
    ecu_thread = threading.Thread(target=run_can_ecu, kwargs={"channel": "uds-can-bus"}, daemon=True)
    ecu_thread.start()
    time.sleep(0.1)

    t = CanTesterClient(channel="uds-can-bus")
    t.set_session(0x03)

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
    print("PASS: full UDS diagnostic session (session control, security access, "
          "RDBI/WDBI, routine control, reset) completed correctly over real CAN + ISO-TP transport")

if __name__ == "__main__":
    test_full_session_over_can()
    print("\nALL CAN INTEGRATION TESTS PASSED")
