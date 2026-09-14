import time
from can_transport import CanUdsTransport, DEFAULT_TESTER_ID, DEFAULT_ECU_ID
from uds_common import ECUState, handle_request, frame_to_hex

def run_can_ecu(channel="uds-can-bus"):
    state = ECUState()
    transport = CanUdsTransport(channel, tx_id=DEFAULT_ECU_ID, rx_id=DEFAULT_TESTER_ID)
    print(f"[ECU] Listening on virtual CAN channel '{channel}' ")
    print(f"      TX ID={hex(DEFAULT_ECU_ID)}, RX ID={hex(DEFAULT_TESTER_ID)}")
    try:
        while True:
            req = transport.receive_uds_message()
            if req is None:
                break
            print(f"[ECU] <- {frame_to_hex(req)}")
            resp = handle_request(state, req)
            print(f"[ECU] -> {frame_to_hex(resp)}")
            transport.send_uds_message(resp)
    except KeyboardInterrupt:
        print("[ECU] Stopped.")
    finally:
        transport.close()
