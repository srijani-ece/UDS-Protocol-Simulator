# UDS (ISO 14229) Protocol Simulator

A Python-based diagnostic tester ↔ ECU simulator implementing UDS request/response handling, diagnostic session state, security access, and CAN-based transport using ISO-TP.

The project started with a TCP transport and was extended to a CAN-frame-level transport while keeping the UDS application logic separated from the transport layer.

## Project overview

The simulator models a diagnostic tester communicating with an ECU.

The ECU behaves like a security-controlled system:

* The tester must enter the appropriate diagnostic session before performing protected operations.
* Read operations can be performed without unlocking security access.
* Write operations and routine control are security-gated.
* The ECU generates a fresh random security seed.
* The tester computes the corresponding key and sends it back.
* An incorrect key is rejected.

The seed/key mechanism is intentionally simplified for simulation purposes. Production ECUs typically use proprietary or cryptographically stronger algorithms.

## Architecture

The project is structured into separate protocol and transport layers:

```text
UDS Application Layer
        │
        ▼
ecu_can.py / tester_can.py
        │
        ▼
can_transport.py
        │
        ▼
ISO-TP (ISO 15765-2)
        │
        ▼
python-can Virtual CAN Bus
```

### Layer responsibilities

| Component | Responsibility |
|---|---|
| `iso_tp.py`                      | Pure ISO-TP framing, segmentation, reassembly, sequence validation, and Flow Control frame handling |
| `can_transport.py`               | CAN transport layer built on `python-can`; sends and receives complete UDS payloads over ISO-TP     |
| `ecu_can.py`                     | ECU-side CAN diagnostic simulator                                                                   |
| `tester_can.py`                  | Tester-side CAN diagnostic client                                                                   |
| `test_can_transport.py`          | Unit/regression tests for ISO-TP and CAN transport behavior                                         |
| `test_uds_over_can.py`           | End-to-end UDS diagnostic session over the CAN transport                                            |
| `ecu_simulator.py` / `tester.py` | Original UDS application implementation used by the simulator                                       |

A key design property is that the UDS request handling logic is separated from the transport mechanism. The CAN transport was integrated without requiring changes to the core `handle_request()` UDS logic.

## Services implemented

| SID    | Service                    | Security         |
| ------ | -------------------------- | ---------------- |
| `0x10` | Diagnostic Session Control | —                |
| `0x11` | ECU Reset                  | —                |
| `0x22` | Read Data By Identifier    | Read access      |
| `0x27` | Security Access (seed/key) | Unlock mechanism |
| `0x2E` | Write Data By Identifier   | Required         |
| `0x31` | Routine Control            | Required         |
| `0x3E` | Tester Present             | —                |

## CAN + ISO-TP Transport Layer

The project implements CAN-frame-level transport using ISO-TP (ISO 15765-2).

The implementation models Classical CAN data frames with up to 8 bytes of payload. ISO-TP allows larger UDS messages to be segmented across multiple CAN frames and reassembled by the receiver.

### ISO-TP frame types

| Frame                  | Purpose                                                                           |
| ---------------------- | --------------------------------------------------------------------------------- |
| Single Frame (SF)      | Carries a complete payload that fits within a single frame                        |
| First Frame (FF)       | Starts a multi-frame transfer and announces the total payload length              |
| Consecutive Frame (CF) | Carries the remaining payload and uses sequence numbers to detect ordering errors |
| Flow Control (FC)      | Receiver response controlling whether the sender continues, waits, or aborts      |

For a multi-frame transfer, the receiver sends a Flow Control frame before the sender continues transmitting Consecutive Frames.

The implementation also supports Flow Control Block Size and STmin pacing.

## Virtual CAN backend

The transport currently uses `python-can`'s **virtual bus backend**.

This provides an actual `python-can` bus interface and `can.Message` objects without requiring a physical CAN adapter or Linux SocketCAN setup. Two independent `CanUdsTransport` instances communicate through the virtual bus.

This makes the transport layer testable in environments where `vcan0` or physical CAN hardware is unavailable.

### Hardware / SocketCAN note

The current implementation is intentionally configured for the `virtual` backend.

Moving to SocketCAN or physical CAN hardware would require environment-specific configuration and testing in addition to changing the `python-can` interface/channel configuration. The protocol and ISO-TP layers are designed to remain independent of that bus backend.

## Transport validation and defensive checks

The CAN/ISO-TP transport includes validation for malformed and invalid protocol states, including:

* Rejecting payloads larger than the supported 12-bit ISO-TP length limit of 4095 bytes.
* Rejecting empty CAN frames.
* Rejecting malformed Single Frames whose claimed payload length exceeds the available data.
* Rejecting First Frames shorter than the required 8-byte CAN frame.
* Rejecting invalid First Frame payload lengths.
* Detecting out-of-order Consecutive Frames through sequence-number validation.
* Rejecting reserved/invalid ISO-TP STmin values.
* Supporting sub-millisecond STmin values in the `0xF1`–`0xF9` range.
* Enforcing Flow Control Block Size.
* Bounding repeated Flow Control `WAIT` frames so a sender cannot wait indefinitely.

These checks are covered by regression tests in `test_can_transport.py`.

## Testing

Run the transport-layer test suite:

```bash
pip install python-can
python3 test_can_transport.py
```

The test suite covers:

* Single-frame ISO-TP round-trip
* Multi-frame segmentation and reassembly
* Consecutive Frame sequence validation
* Flow Control frame formatting
* Two-instance CAN transport communication
* Flow Control Block Size enforcement
* ISO-TP payload length limits
* Malformed frame rejection
* Malformed First Frame rejection
* Invalid STmin rejection
* Bounded repeated Flow Control `WAIT`

Run the end-to-end UDS-over-CAN test:

```bash
python3 test_uds_over_can.py
```

This exercises the diagnostic session over the CAN transport, including session control, security access, Read Data By Identifier, Write Data By Identifier, routine control, Tester Present, and ECU reset behaviour.

## Test Outputs - 
### Full automated suite: 
@srijani-ece ➜ /workspaces/UDS-Protocol-Simulator (main) $ pytest -v
=========================================================== test session starts===========================================================
platform linux -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/py-utils/venvs/pytest/bin/python
cachedir: .pytest_cache
rootdir: /workspaces/UDS-Protocol-Simulator
plugins: anyio-4.14.2
collected 23 items                                                                                                                        

test_can_transport.py::test_single_frame_roundtrip PASSED                                                                           [  4%]
test_can_transport.py::test_multi_frame_roundtrip PASSED                                                                            [  8%]
test_can_transport.py::test_sequence_error_detected PASSED                                                                          [ 13%]
test_can_transport.py::test_flow_control_frame_format PASSED                                                                        [ 17%]
test_can_transport.py::test_real_can_multi_frame_transfer PASSED                                                                    [ 21%]
test_can_transport.py::test_flow_control_block_size_actually_enforced PASSED                                                        [ 26%]
test_can_transport.py::test_payload_over_4095_bytes_rejected PASSED                                                                 [ 30%]
test_can_transport.py::test_malformed_empty_frame_rejected PASSED                                                                   [ 34%]
test_can_transport.py::test_malformed_first_frame_rejected PASSED                                                                   [ 39%]
test_can_transport.py::test_invalid_st_min_rejected PASSED                                                                          [ 43%]
test_can_transport.py::test_repeated_fc_wait_is_bounded PASSED                                                                      [ 47%]
test_can_transport.py::test_fc_wait_resets_between_bursts PASSED                                                                    [ 52%]
test_can_transport.py::test_block_size_state_does_not_leak_across_messages PASSED                                                   [ 56%]
test_can_transport.py::test_sequence_number_wraps_past_15 PASSED                                                                    [ 60%]
test_uds.py::test_session_control_valid PASSED                                                                                      [ 65%]
test_uds.py::test_session_control_invalid_subfunction PASSED                                                                        [ 69%]
test_uds.py::test_write_without_security_denied PASSED                                                                              [ 73%]
test_uds.py::test_security_access_wrong_key_rejected PASSED                                                                         [ 78%]
test_uds.py::test_security_access_correct_key_unlocks PASSED                                                                        [ 82%]
test_uds.py::test_security_access_key_without_seed_rejected PASSED                                                                  [ 86%]
test_uds.py::test_read_unsupported_did_out_of_range PASSED                                                                          [ 91%]
test_uds.py::test_end_to_end_full_session PASSED                                                                                    [ 95%]
test_uds_over_can.py::test_full_session_over_can PASSED                                                                             [100%]

=========================================================== 23 passed in 1.42s============================================================
### CAN/ISO-TP:
@srijani-ece ➜ /workspaces/UDS-Protocol-Simulator (main) $ pytest test_can_transport.py -v
=========================================================== test session starts===========================================================
platform linux -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/py-utils/venvs/pytest/bin/python
cachedir: .pytest_cache
rootdir: /workspaces/UDS-Protocol-Simulator
plugins: anyio-4.14.2
collected 14 items                                                                                                                        

test_can_transport.py::test_single_frame_roundtrip PASSED                                                                           [  7%]
test_can_transport.py::test_multi_frame_roundtrip PASSED                                                                            [ 14%]
test_can_transport.py::test_sequence_error_detected PASSED                                                                          [ 21%]
test_can_transport.py::test_flow_control_frame_format PASSED                                                                        [ 28%]
test_can_transport.py::test_real_can_multi_frame_transfer PASSED                                                                    [ 35%]
test_can_transport.py::test_flow_control_block_size_actually_enforced PASSED                                                        [ 42%]
test_can_transport.py::test_payload_over_4095_bytes_rejected PASSED                                                                 [ 50%]
test_can_transport.py::test_malformed_empty_frame_rejected PASSED                                                                   [ 57%]
test_can_transport.py::test_malformed_first_frame_rejected PASSED                                                                   [ 64%]
test_can_transport.py::test_invalid_st_min_rejected PASSED                                                                          [ 71%]
test_can_transport.py::test_repeated_fc_wait_is_bounded PASSED                                                                      [ 78%]
test_can_transport.py::test_fc_wait_resets_between_bursts PASSED                                                                    [ 85%]
test_can_transport.py::test_block_size_state_does_not_leak_across_messages PASSED                                                   [ 92%]
test_can_transport.py::test_sequence_number_wraps_past_15 PASSED                                                                    [100%]

=========================================================== 14 passed in 0.37s============================================================
### UDS core tests:
@srijani-ece ➜ /workspaces/UDS-Protocol-Simulator (main) $ pytest test_uds.py -v
=========================================================== test session starts===========================================================
platform linux -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/py-utils/venvs/pytest/bin/python
cachedir: .pytest_cache
rootdir: /workspaces/UDS-Protocol-Simulator
plugins: anyio-4.14.2
collected 8 items                                                                                                                         

test_uds.py::test_session_control_valid PASSED                                                                                      [ 12%]
test_uds.py::test_session_control_invalid_subfunction PASSED                                                                        [ 25%]
test_uds.py::test_write_without_security_denied PASSED                                                                              [ 37%]
test_uds.py::test_security_access_wrong_key_rejected PASSED                                                                         [ 50%]
test_uds.py::test_security_access_correct_key_unlocks PASSED                                                                        [ 62%]
test_uds.py::test_security_access_key_without_seed_rejected PASSED                                                                  [ 75%]
test_uds.py::test_read_unsupported_did_out_of_range PASSED                                                                          [ 87%]
test_uds.py::test_end_to_end_full_session PASSED                                                                                    [100%]

============================================================ 8 passed in 0.35s============================================================
### UDS-over-CAN integration:
@srijani-ece ➜ /workspaces/UDS-Protocol-Simulator (main) $ pytest test_uds_over_can.py -v
=========================================================== test session starts===========================================================
platform linux -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/py-utils/venvs/pytest/bin/python
cachedir: .pytest_cache
rootdir: /workspaces/UDS-Protocol-Simulator
plugins: anyio-4.14.2
collected 1 item                                                                                                                          

test_uds_over_can.py::test_full_session_over_can PASSED                                                                             [100%]

============================================================ 1 passed in 0.56s============================================================
### Security Access seed/key exchange, Correct key unlocks ECU, Invalid key rejection, 3-attempt security lockout, Lockout enforcement, ECU Reset resets session, ECU Reset locks security, ECU Reset clears pending_seed (see below), S3 timeout, Read DID, Write denied while locked, Write allowed after unlock, Read-after-write state change. 
PYint("=" * 60)ALIDATION COMPLETE")sponse[3])g")--------------d")
============================================================
MANUAL UDS VALIDATION
============================================================

[1] Security Access - correct key
Session: 50 03
Seed response: 67 01 79 ec
Seed: 0x79ec
Calculated key: 0xdc49
Unlock response: 67 02
Security unlocked: True

[2] Security Access - three wrong keys
Wrong-key attempt 1: 7f 27 35
Wrong-key attempt 2: 7f 27 35
Wrong-key attempt 3: 7f 27 36

[3] Lockout enforcement
Request seed during lockout: 7f 27 37

[4/5] ECU Reset clears security state and pending seed
Pending seed before reset: 35295
Unlock response: 67 02
Security before reset: True
Pending seed before reset: None
Reset response: 51 01
Session after reset: 0x1
Security after reset: False
Pending seed after reset: None

[6] S3 session timeout
Enter extended session: 50 03
Session immediately after: 0x3
Waiting 6 seconds...
Tester Present: 7e 00
Session after timeout: 0x1
Security unlocked: False

[7] Read/write DID
Initial read: 62 f0 0d 2a
Initial speed: 42
Write before unlock: 7f 2e 33
Write after unlock: 6e f0 0d
Read after write: 62 f0 0d 55
Speed after write: 85
### ECU Reset clears a live pending_seed:
PY
Seed response: 67 01 64 54
Pending seed before reset: 25684
Reset response: 51 01
Pending seed after reset: None
Session after reset: 0x1
Security after reset: False
### CAN end-to-end communication:
@srijani-ece ➜ /workspaces/UDS-Protocol-Simulator (main) $ pytest test_uds_over_can.py -v -s
=========================================================== test session starts===========================================================
platform linux -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/py-utils/venvs/pytest/bin/python
cachedir: .pytest_cache
rootdir: /workspaces/UDS-Protocol-Simulator
plugins: anyio-4.14.2
collected 1 item                                                                                                                          

test_uds_over_can.py::test_full_session_over_can [ECU] Listening on virtual CAN channel 'test-integration-channel' 
      TX ID=0x7e8, RX ID=0x7e0
[Tester-CAN] -> 10 03
[ECU] <- 10 03
[ECU] -> 50 03
[Tester-CAN] <- 50 03
[Tester-CAN] -> 22 F0 0D
[ECU] <- 22 F0 0D
[ECU] -> 62 F0 0D 2A
[Tester-CAN] <- 62 F0 0D 2A
[Tester-CAN] -> 2E F0 0D 64
[ECU] <- 2E F0 0D 64
[ECU] -> 7F 2E 33
[Tester-CAN] <- 7F 2E 33
[Tester-CAN] -> 27 01
[ECU] <- 27 01
[ECU] -> 67 01 33 6E
[Tester-CAN] <- 67 01 33 6E
[Tester-CAN] -> 27 02 96 CB
[ECU] <- 27 02 96 CB
[ECU] -> 67 02
[Tester-CAN] <- 67 02
[Tester-CAN] -> 2E F0 0D 64
[ECU] <- 2E F0 0D 64
[ECU] -> 6E F0 0D
[Tester-CAN] <- 6E F0 0D
[Tester-CAN] -> 22 F0 0D
[ECU] <- 22 F0 0D
[ECU] -> 62 F0 0D 64
[Tester-CAN] <- 62 F0 0D 64
[Tester-CAN] -> 31 01 02 03
[ECU] <- 31 01 02 03
[ECU] -> 71 01 02 03
[Tester-CAN] <- 71 01 02 03
[Tester-CAN] -> 3E 00
[ECU] <- 3E 00
[ECU] -> 7E 00
[Tester-CAN] <- 7E 00
[Tester-CAN] -> 11 01
[ECU] <- 11 01
[ECU] -> 51 01
[Tester-CAN] <- 51 01
PASS: full UDS diagnostic session (session control, security access, RDBI/WDBI, routine control, reset) completed correctly over real CAN + ISO-TP transport
PASSED

============================================================ 1 passed in 0.56s============================================================
### ISO-TP multi-frame transfer:
@srijani-ece ➜ /workspaces/UDS-Protocol-Simulator (main) $ pytest test_can_transport.py -v -s
=========================================================== test session starts===========================================================
platform linux -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/py-utils/venvs/pytest/bin/python
cachedir: .pytest_cache
rootdir: /workspaces/UDS-Protocol-Simulator
plugins: anyio-4.14.2
collected 14 items                                                                                                                        

test_can_transport.py::test_single_frame_roundtrip PASS: single-frame message correctly built and reassembled
PASSED
test_can_transport.py::test_multi_frame_roundtrip PASS: 20-byte message split into 3 CAN frames and correctly reassembled
PASSED
test_can_transport.py::test_sequence_error_detected PASS: out-of-order Consecutive Frame correctly detected and rejected
PASSED
test_can_transport.py::test_flow_control_frame_format PASS: Flow Control frame correctly encodes status/block-size/STmin
PASSED
test_can_transport.py::test_real_can_multi_frame_transfer PASS: real 25-byte UDS message sent over virtual CAN bus, correctly split, Flow-Control-negotiated, and reassembled on the ECU side
PASSED
test_can_transport.py::test_flow_control_block_size_actually_enforced PASS: Block Size=2 genuinely enforced — sender paused for 3 separateFlow Control round-trips across 5 Consecutive Frames, not sent as one burst
PASSED
test_can_transport.py::test_payload_over_4095_bytes_rejected PASS: payload exceeding ISO-TP's 4095-byte limit correctly rejected
PASSED
test_can_transport.py::test_malformed_empty_frame_rejected PASS: empty/malformed CAN frame correctly rejected instead of crashing
PASSED
test_can_transport.py::test_malformed_first_frame_rejected PASS: malformed First Frame correctly rejected
PASSED
test_can_transport.py::test_invalid_st_min_rejected PASS: reserved ISO-TP STmin correctly rejected
PASSED
test_can_transport.py::test_repeated_fc_wait_is_bounded PASS: repeated Flow Control WAIT correctly bounded
PASSED
test_can_transport.py::test_fc_wait_resets_between_bursts PASS: Flow Control WAIT counter resets after a CONTINUE
PASSED
test_can_transport.py::test_block_size_state_does_not_leak_across_messages PASS: Flow Control block-size counter does not leak across messages on the same transport instance
PASSED
test_can_transport.py::test_sequence_number_wraps_past_15 PASS: Consecutive Frame sequence number correctly wraps past 15 back to 0/1
PASSED

=========================================================== 14 passed in 0.29s============================================================
### CAN Flow Control / Block Size:
@srijani-ece ➜ /workspaces/UDS-Protocol-Simulator (main) $ pytest test_can_transport.py -v -s
=========================================================== test session starts===========================================================
platform linux -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/py-utils/venvs/pytest/bin/python
cachedir: .pytest_cache
rootdir: /workspaces/UDS-Protocol-Simulator
plugins: anyio-4.14.2
collected 14 items                                                                                                                        

test_can_transport.py::test_single_frame_roundtrip PASS: single-frame message correctly built and reassembled
PASSED
test_can_transport.py::test_multi_frame_roundtrip PASS: 20-byte message split into 3 CAN frames and correctly reassembled
PASSED
test_can_transport.py::test_sequence_error_detected PASS: out-of-order Consecutive Frame correctly detected and rejected
PASSED
test_can_transport.py::test_flow_control_frame_format PASS: Flow Control frame correctly encodes status/block-size/STmin
PASSED
test_can_transport.py::test_real_can_multi_frame_transfer PASS: real 25-byte UDS message sent over virtual CAN bus, correctly split, Flow-Control-negotiated, and reassembled on the ECU side
PASSED
test_can_transport.py::test_flow_control_block_size_actually_enforced PASS: Block Size=2 genuinely enforced — sender paused for 3 separateFlow Control round-trips across 5 Consecutive Frames, not sent as one burst
PASSED
test_can_transport.py::test_payload_over_4095_bytes_rejected PASS: payload exceeding ISO-TP's 4095-byte limit correctly rejected
PASSED
test_can_transport.py::test_malformed_empty_frame_rejected PASS: empty/malformed CAN frame correctly rejected instead of crashing
PASSED
test_can_transport.py::test_malformed_first_frame_rejected PASS: malformed First Frame correctly rejected
PASSED
test_can_transport.py::test_invalid_st_min_rejected PASS: reserved ISO-TP STmin correctly rejected
PASSED
test_can_transport.py::test_repeated_fc_wait_is_bounded PASS: repeated Flow Control WAIT correctly bounded
PASSED
test_can_transport.py::test_fc_wait_resets_between_bursts PASS: Flow Control WAIT counter resets after a CONTINUE
PASSED
test_can_transport.py::test_block_size_state_does_not_leak_across_messages PASS: Flow Control block-size counter does not leak across messages on the same transport instance
PASSED
test_can_transport.py::test_sequence_number_wraps_past_15 PASS: Consecutive Frame sequence number correctly wraps past 15 back to 0/1
PASSED

=========================================================== 14 passed in 0.29s============================================================

## What I'd add next

* `0x34 / 0x36 / 0x37` — UDS Request Download / Transfer Data / Request Transfer Exit for an OTA-style firmware update flow.
* Interactive diagnostic tester CLI.
* Additional negative-path and timeout tests.
* SocketCAN / physical CAN hardware validation.

## Project status

The simulator currently provides:

* UDS diagnostic services:
  * Diagnostic Session Control (`0x10`)
  * ECU Reset (`0x11`)
  * Read Data By Identifier (`0x22`)
  * Security Access (`0x27`)
  * Write Data By Identifier (`0x2E`)
  * Routine Control (`0x31`)
  * Tester Present (`0x3E`)
* Diagnostic session and security state management
* Security Access seed/key exchange
* Failed-key attempt tracking and timed security lockout
* S3 session timeout handling
* ECU reset state handling
* TCP-based UDS communication
* CAN transport using `python-can`
* ISO-TP segmentation and reassembly
* Single- and multi-frame CAN message handling
* Flow Control negotiation
* Flow Control Block Size enforcement
* STmin decoding and pacing
* Defensive ISO-TP protocol validation
* Virtual CAN-based integration testing
* End-to-end UDS-over-CAN testing
* Automated regression testing with pytest
