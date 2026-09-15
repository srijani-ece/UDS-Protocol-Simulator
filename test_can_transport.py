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


def test_flow_control_block_size_actually_enforced():
    """
    This is the test that proves fix #2: not just that a Block Size
    number can be encoded into a Flow Control frame (already covered
    by test_flow_control_frame_format), but that the SENDER genuinely
    pauses and waits for a fresh Flow Control frame after each block,
    instead of blasting every Consecutive Frame through on the first
    'go ahead'.
    """
    channel = "test-channel-blocksize"

    # 41 bytes -> First Frame carries 6, leaving exactly 35 bytes ->
    # exactly 5 Consecutive Frames (35 / 7). With block_size=2, that's
    # 3 blocks (2, 2, 1) -> receiver must send 3 separate Flow Control
    # frames total (one to start, one after each full block of 2).
    payload = bytes(range(41))

    received_holder = {}
    fc_frames_sent_by_receiver = {"count": 0}

    def ecu_side():
        ecu_transport = CanUdsTransport(channel, tx_id=DEFAULT_ECU_ID, rx_id=DEFAULT_TESTER_ID)

        # Wrap _send_can_frame so we can count how many Flow Control
        # frames the receiver actually sends, without changing its
        # real behavior at all.
        original_send = ecu_transport._send_can_frame
        def counting_send(data):
            if (data[0] >> 4) == 0x3:  # Flow Control frame type
                fc_frames_sent_by_receiver["count"] += 1
            original_send(data)
        ecu_transport._send_can_frame = counting_send

        received_holder["data"] = ecu_transport.receive_uds_message(fc_block_size=2, fc_st_min=0)
        ecu_transport.close()

    ecu_thread = threading.Thread(target=ecu_side, daemon=True)
    ecu_thread.start()
    time.sleep(0.2)

    tester_transport = CanUdsTransport(channel, tx_id=DEFAULT_TESTER_ID, rx_id=DEFAULT_ECU_ID)
    tester_transport.send_uds_message(payload)
    tester_transport.close()

    ecu_thread.join(timeout=3.0)

    assert received_holder.get("data") == payload, "Reassembled message doesn't match original"
    assert fc_frames_sent_by_receiver["count"] == 3, (
        f"Expected exactly 3 Flow Control round-trips for 5 CFs at "
        f"block_size=2 (2+2+1), but got {fc_frames_sent_by_receiver['count']} — "
        f"the sender is not actually respecting Block Size."
    )
    print(f"PASS: Block Size=2 genuinely enforced — sender paused for "
          f"{fc_frames_sent_by_receiver['count']} separate Flow Control "
          f"round-trips across 5 Consecutive Frames, not sent as one burst")


def test_payload_over_4095_bytes_rejected():
    """Proves fix #1: the 12-bit First Frame length limit is now enforced."""
    too_big = bytes(4096)
    try:
        build_frames(too_big)
        assert False, "should have rejected a payload over 4095 bytes"
    except ValueError as e:
        assert "4095" in str(e)
    print("PASS: payload exceeding ISO-TP's 4095-byte limit correctly rejected")


def test_malformed_empty_frame_rejected():
    """Proves fix #11: defensive validation on malformed frames."""
    receiver = IsoTpReceiver()
    try:
        receiver.receive_frame(b"")
        assert False, "should have rejected an empty frame"
    except ValueError as e:
        assert "Empty" in str(e)
    print("PASS: empty/malformed CAN frame correctly rejected instead of crashing")

def test_malformed_first_frame_rejected():
    """Rejects a First Frame that is shorter than the required 8-byte CAN frame."""
    receiver = IsoTpReceiver()

    malformed_ff = bytes([0x10, 0x08, 0xAA, 0xBB])

    try:
        receiver.receive_frame(malformed_ff)
        assert False, "should have rejected a malformed First Frame"
    except ValueError as e:
        assert "Malformed First Frame" in str(e)

    print("PASS: malformed First Frame correctly rejected")

def test_invalid_st_min_rejected():
    """Rejects reserved ISO-TP STmin values instead of silently treating them as zero."""
    try:
        CanUdsTransport._decode_st_min(0x80)
        assert False, "should have rejected reserved STmin value"
    except ValueError as e:
        assert "Invalid/reserved ISO-TP STmin" in str(e)

    print("PASS: reserved ISO-TP STmin correctly rejected")

def test_repeated_fc_wait_is_bounded():
    """Rejects an indefinitely waiting receiver after the configured limit."""
    transport = CanUdsTransport.__new__(CanUdsTransport)
    transport._send_can_frame = lambda data: None

    wait_frame = bytes([0x31, 0x00, 0x00])  # FC WAIT, BS=0, STmin=0
    transport._receive_can_frame = lambda: wait_frame

    payload = bytes(range(20))

    try:
        transport.send_uds_message(payload)
        assert False, "should have rejected repeated FC WAIT frames"
    except TimeoutError as e:
        assert "too many consecutive Flow Control WAIT" in str(e)

    print("PASS: repeated Flow Control WAIT correctly bounded")

if __name__ == "__main__":
    test_single_frame_roundtrip()
    test_multi_frame_roundtrip()
    test_sequence_error_detected()
    test_flow_control_frame_format()
    test_real_can_multi_frame_transfer()
    test_flow_control_block_size_actually_enforced()
    test_payload_over_4095_bytes_rejected()
    test_malformed_empty_frame_rejected()
    test_malformed_first_frame_rejected()
    test_invalid_st_min_rejected()
    test_repeated_fc_wait_is_bounded()
    print("\nALL TESTS PASSED")