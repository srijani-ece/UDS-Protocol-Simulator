import time

from can_transport import (
    CanUdsTransport,
    DEFAULT_TESTER_ID,
    DEFAULT_ECU_ID,
)
from ecu_simulator import ECUState, handle_request
from uds_common import frame_to_hex


def run_can_ecu(channel="uds-can-bus"):
    state = ECUState()

    transport = CanUdsTransport(
        channel,
        tx_id=DEFAULT_ECU_ID,
        rx_id=DEFAULT_TESTER_ID,
    )

    print(f"[ECU] Listening on virtual CAN channel '{channel}' ")
    print(
        f"      TX ID={hex(DEFAULT_ECU_ID)}, "
        f"RX ID={hex(DEFAULT_TESTER_ID)}"
    )

    try:
        while True:
            try:
                req = transport.receive_uds_message()

            except TimeoutError:
                # Nobody sent anything in the last `timeout` seconds.
                # That's normal idle time for a bus, not a shutdown
                # signal — just go back and keep listening.
                continue

            print(f"[ECU] <- {frame_to_hex(req)}")

            try:
                resp = handle_request(state, req)

            except Exception as e:
                # A bad/unexpected request should never kill the ECU —
                # a real ECU keeps serving the next request.
                print(f"[ECU] !! error handling request: {e}")
                continue

            if not resp:
                # Empty response means the tester set the
                # suppressPosRspMsgIndicationBit — say nothing back.
                print("[ECU] (response suppressed by tester)")
                continue

            print(f"[ECU] -> {frame_to_hex(resp)}")
            transport.send_uds_message(resp)

    except KeyboardInterrupt:
        print("[ECU] Stopped.")

    finally:
        transport.close()