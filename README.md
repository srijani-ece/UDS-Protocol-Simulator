# UDS (ISO 14229) Protocol Simulator

A working diagnostic tester ↔ ECU simulation in Python, implementing
real UDS request/response framing, session state, and a security
access seed/key handshake.

## Breaking it down in a simple version:

Imagine your car's ECU is a strict security guard: wrong session, guard
won't discuss sensitive topics. Right session but no ID shown yet, guard
lets you look around (read data) but not touch anything (write data,
run routines). Show a fake ID (wrong key), guard rejects you and says
exactly why. Show the real ID (key computed correctly from a one-time
random seed), you're trusted for the rest of the visit.

## Why the seed/key handshake matters

The seed changes every session, so recording an old successful
handshake and replaying it later won't work cause the old key doesn't
match the new seed. This project uses a simplified stand-in algorithm;
real manufacturers use proprietary, much harder-to-reverse math here.

## Files
(UPDATED)

| File | What it does |
|---|---|
| `iso_tp.py` | Pure ISO-TP framing logic: Single/First/Consecutive/Flow-Control frame encode & decode, no networking |
| `can_transport.py` | Wraps `python-can`, sends/receives full UDS messages, handling ISO-TP segmentation transparently |
| `test_can_transport.py` | 4 pure-logic tests + 1 real two-instance CAN bus transfer test |
| `ecu_can.py` | The UDS ECU simulator, now listening on this CAN transport instead of TCP |
| `tester_can.py` | The UDS tester client, now sending over this CAN transport instead of TCP |
| `test_uds_over_can.py` | Full UDS diagnostic session (session control, security access, RDBI/WDBI, routine control, reset) proven end-to-end over CAN |

## Services implemented

| SID | Service |
|---|---|
| `0x10` | Diagnostic Session Control |
| `0x11` | ECU Reset |
| `0x22` | Read Data By Identifier |
| `0x27` | Security Access (seed/key) |
| `0x2E` | Write Data By Identifier (security-gated) |
| `0x31` | Routine Control (security-gated) |
| `0x3E` | Tester Present |

## How to run it

```bash
python3 test_uds.py
```
## Output:
<img width="675" height="579" alt="Screenshot (40)" src="https://github.com/user-attachments/assets/9f49a44f-9adf-4128-8801-3efe5314b261" />

<img width="634" height="620" alt="Screenshot (41)" src="https://github.com/user-attachments/assets/293abca8-cba8-492c-9b39-b0f6d6bfa2c4" />


## What I'd add next

- - ~~Real CAN transport (python-can + vcan0) instead of TCP~~ **Done**, see `iso_tp.y` / `can_transport.py` / `test_can_transport.py` 
- 0x34/0x36/0x37 (OTA firmware update flow)
- Interactive CLI for the tester
- - ~~Wire this into `ecu_simulator.py` / `tester.py`~~ — **Done**, see `ecu_can.py` / `tester_can.py` / `test_uds_over_can.py`. `handle_request()` (the actual UDS logic) needed zero changes.

# CAN Bus + ISO-TP Transport Layer (ISO 15765-2)

An upgrade to the UDS Protocol Simulator: real CAN-frame-level
transport with ISO-TP segmentation and reassembly, replacing the
original plain-TCP transport. UDS messages longer than 7 bytes are now
genuinely split across multiple 8-byte CAN frames and reassembled, including a real, two-directional Flow Control handshake instead of being sent as one arbitrarily-sized chunk over a socket.
This uses `python-can`'s **virtual** bus backend, not real SocketCAN
(`vcan0`). Real SocketCAN needs a Linux kernel module and a privileged
container, which is currently not available. The virtual backend is a real
`python-can` feature (used in python-can's own test suite) that is the same
`can.Message` objects, the same API, and the same ISO-TP logic sitting on top of
it. Switching to real hardware or SocketCAN later is a **updating the code to** (`interface="socketcan", channel="vcan0"` instead of `interface="virtual"`)

## The 4 frame types (ISO 15765-2)

| Frame | Purpose |
|---|---|
| Single Frame (SF) | Whole message fits in ≤7 bytes: sent as-is |
| First Frame (FF) | Message too big: announces total length, carries first 6 bytes |
| Consecutive Frame (CF) | Carries the next 7 bytes, numbered 0-15 (wraps) so dropped or reordered frames are detectable |
| Flow Control (FC) | Sent by the **receiver** back to the sender: "continue," "wait," or "abort," plus pacing controls |

## What's verified: 

- 20-byte message correctly splits into exactly 3 frames (1 FF + 2 CF) and reassembles byte-for-byte
- An out-of-order Consecutive Frame is correctly detected and rejected
- A real 25-byte message sent between two independent `CanUdsTransport` instances (genuinely separate objects, communicating only via the virtual CAN bus, not by sharing memory), including the ECU side correctly sending back a real Flow Control frame before the sender continues.

- ## How to run it

```bash
pip install python-can
python3 test_can_transport.py
```
## Output:
<img width="975" height="460" alt="uds_ps_test_can_transportpy" src="https://github.com/user-attachments/assets/8828c93a-4d48-4576-b20d-297020ac2a26" />

## Wire CAN Transport into ECU Simulator (output):
<img width="819" height="460" alt="UDS_3RD_UPDATEa" src="https://github.com/user-attachments/assets/6cd36f38-8dd7-41ca-b8f3-fb32006f1a4a" />
<img width="942" height="527" alt="UDS_3RD_UPDATEb" src="https://github.com/user-attachments/assets/4244004e-c956-4f1e-8b12-cfae971d0c07" />
