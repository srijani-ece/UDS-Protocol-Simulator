# UDS (ISO 14229) Protocol Simulator

A working diagnostic tester ↔ ECU simulation in Python, implementing
real UDS request/response framing, session state, and a security
access seed/key handshake.

## The simple version

Imagine your car's ECU is a strict security guard: wrong session, guard
won't discuss sensitive topics. Right session but no ID shown yet, guard
lets you look around (read data) but not touch anything (write data,
run routines). Show a fake ID (wrong key), guard rejects you and says
exactly why. Show the real ID (key computed correctly from a one-time
random seed), you're trusted for the rest of the visit.

## Why the seed/key handshake matters

The seed changes every session, so recording an old successful
handshake and replaying it later won't work — the old key doesn't
match the new seed. This project uses a simplified stand-in algorithm;
real manufacturers use proprietary, much harder-to-reverse math here.

## Files

| File | What it does |
|---|---|
| `uds_common.py` | Shared protocol constants |
| `ecu_simulator.py` | The ECU: state machine enforcing session + security rules |
| `tester.py` | The diagnostic client |
| `test_uds.py` | 6 unit tests + 1 full end-to-end socket test |

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

## What I'd add next

- Real CAN transport (python-can + vcan0) instead of TCP
- 0x34/0x36/0x37 (OTA firmware update flow)
- Interactive CLI for the tester
