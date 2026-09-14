"""
ecu_can.py — the same ECU state machine from ecu_simulator.py, now
listening on a real CAN bus (via ISO-TP) instead of a plain TCP
socket.

ELI5: This is the exact same "security guard" logic as before — same
rules, same seed/key handshake, same session gating. The ONLY thing
that changed is how messages physically arrive and leave: instead of
a network socket, it's now real 8-byte CAN frames, transparently
stitched together by the ISO-TP layer underneath. `handle_request()`
itself — the actual UDS brain — didn't need a single line changed,
because it was written from the start to only care about bytes in,
bytes out. That separation is exactly why swapping the transport was
possible without touching the protocol logic at all.
"""

from can_transport import CanUdsTransport, DEFAULT_TESTER_ID, DEFAULT_ECU_ID
from ecu_simulator import ECUState, handle_request
from uds_common import frame_to_hex


def serve_can(channel: str = "uds-can-bus"):
    state = ECUState()
    transport = CanUdsTransport(channel, tx_id=DEFAULT_ECU_ID, rx_id=DEFAULT_TESTER_ID)
    print(f"[ECU-CAN] listening on virtual CAN channel '{channel}' "
          f"(TX ID={hex(DEFAULT_ECU_ID)}, RX ID={hex(DEFAULT_TESTER_ID)})")

    try:
        while True:
            req = transport.receive_uds_message()
            print(f"[ECU-CAN] <- {frame_to_hex(req)}")
            resp = handle_request(state, req)
            print(f"[ECU-CAN] -> {frame_to_hex(resp)}")
            transport.send_uds_message(resp)
    finally:
        transport.close()


if __name__ == "__main__":
    serve_can()
