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

This exercises the diagnostic session over the CAN transport, including session control, security access, Read Data By Identifier, Write Data By Identifier, routine control, Tester Present, and ECU reset behavior.

## Test output
## What I'd add next

* `0x34 / 0x36 / 0x37` — UDS Request Download / Transfer Data / Request Transfer Exit for an OTA-style firmware update flow.
* Interactive diagnostic tester CLI.
* Additional negative-path and timeout tests.
* SocketCAN / physical CAN hardware validation.

## Project status

The simulator currently provides:

* UDS diagnostic services
* Session and security state handling
* CAN transport using `python-can`
* ISO-TP segmentation and reassembly
* Flow Control negotiation
* Block Size enforcement
* STmin decoding and pacing
* Defensive protocol validation
* End-to-end UDS-over-CAN testing
