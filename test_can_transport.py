"""
test_can_transport.py — proves the ISO-TP layer actually works:
correct splitting, correct reassembly, correct sequence-error
detection, and a real two-directional Flow Control handshake over an
actual (virtual) CAN bus with two independent transport instances.
"""

import threading
import time

from iso_tp import build_frames, build_flow_control_frame, IsoTpReceiver, FC_CONTINUE
from can_transport import CanUdsTransport, DEFAULT_TESTER_ID, DEFAULT_ECU_ID


# ─────────────────────────────────────────────────────────────────────
# Layer 1: pure ISO-TP framing logic, no CAN bus involved
# ─────────────────────────────────────────────────────────────────────

def test_single_frame_roundtrip():
    payload = bytes([0x62, 0xF0, 0x0D, 0x2A])  # 4 bytes — fits in one frame
    frames = build_frames(payload)
    assert len(frames) == 1
    assert frames[0][0] >> 4 == 0x0  # Single Frame type
    assert frames[0][0] & 0x0F == len(payload)

    receiver = IsoTpReceiver()
    result = receiver.receive_frame(frames[0])
    assert result == payload
    print("PASS: single-frame message correctly built and reassembled")


def test_multi_frame_roundtrip():
    # 20 bytes — too big for one CAN frame, forces First Frame + 2 Consecutive Frames
    payload = bytes(range(20))
    frames = build_frames(payload)
    assert len(frames) == 3  # 1 FF (6 bytes) + 2 CF (7+7 bytes) = 20 bytes total

    receiver = IsoTpReceiver()
    result = None
    for frame in frames:
        r = receiver.receive_frame(frame)
        if r is not None:
            result = r
    assert result == payload
    print(f"PASS: {len(payload)}-byte message split into {len(frames)} CAN frames and correctly reassembled")


def test_sequence_error_detected():
    payload = bytes(range(20))
    frames = build_frames(payload)
    receiver = IsoTpReceiver()
    receiver.receive_frame(frames[0])  # First Frame — OK
    # Deliberately feed Consecutive Frame #2 before #1 — should be caught
    try:
        receiver.receive_frame(frames[2])
        assert False, "should have raised a sequence error"
    except ValueError as e:
        assert "sequence error" in str(e)
    print("PASS: out-of-order Consecutive Frame correctly detected and rejected")


def test_flow_control_frame_format():
    fc = build_flow_control_frame(FC_CONTINUE, block_size=8, st_min=10)
    assert fc[0] >> 4 == 0x3        # Flow Control type
    assert fc[0] & 0x0F == FC_CONTINUE
    assert fc[1] == 8                # block size
    assert fc[2] == 10               # STmin
    print("PASS: Flow Control frame correctly encodes status/block-size/STmin")


# ─────────────────────────────────────────────────────────────────────
# Layer 2: real two-way CAN transport, two independent transport
# instances, genuine Flow Control handshake over the (virtual) bus
# ─────────────────────────────────────────────────────────────────────

def test_real_can_multi_frame_transfer():
    channel = "test-channel-1"

    # 25-byte payload — realistic size for e.g. a multi-DID read response,
    # definitely requires the full First Frame + Flow Control + Consecutive
    # Frame sequence, not just a Single Frame shortcut.
    big_payload = bytes([i % 256 for i in range(25)])

    received_holder = {}

    def ecu_side():
        ecu_transport = CanUdsTransport(channel, tx_id=DEFAULT_ECU_ID, rx_id=DEFAULT_TESTER_ID)
        received_holder["data"] = ecu_transport.receive_uds_message()
        ecu_transport.close()

    ecu_thread = threading.Thread(target=ecu_side, daemon=True)
    ecu_thread.start()
    time.sleep(0.2)  # let the ECU side start listening first

    tester_transport = CanUdsTransport(channel, tx_id=DEFAULT_TESTER_ID, rx_id=DEFAULT_ECU_ID)
    tester_transport.send_uds_message(big_payload)
    tester_transport.close()

    ecu_thread.join(timeout=3.0)

    assert received_holder.get("data") == big_payload, \
        f"Reassembled message doesn't match original: got {received_holder.get('data')}"
    print(f"PASS: real {len(big_payload)}-byte UDS message sent over virtual CAN bus, "
          f"correctly split, Flow-Control-negotiated, and reassembled on the ECU side")


if __name__ == "__main__":
    test_single_frame_roundtrip()
    test_multi_frame_roundtrip()
    test_sequence_error_detected()
    test_flow_control_frame_format()
    test_real_can_multi_frame_transfer()
    print("\nALL TESTS PASSED")
