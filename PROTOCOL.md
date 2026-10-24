# Observed Trek 4200 Bluetooth protocol

Recovered through analysis of FSpower Android 1.0.5 (`com.hipower.hems`), passive BLE capture on the owner's Trek 4200, cross-checking decoded readings against the app, and an independent client. This document describes observations, not a vendor specification. No application-layer account credential was needed for the tested session.

Service: `000000ff-0000-1000-8000-00805f9b34fb`.
Shared write/notify characteristic: `0000ff01-0000-1000-8000-00805f9b34fb`.
Use writes **with response**; this matches the actual ATT capture. Subscribe before the handshake. The tested request is 86 bytes; require MTU ≥89. The independent Windows reader negotiated 517.

## Outer frame

| Bytes | Meaning |
|---|---|
| 0–1 | `A5 5A` |
| 2–3 | Total length, LE16 |
| 4–7 | Opaque sequence |
| 8–9 | Request `04 01`; observed reply `03 01` |
| 10–34 | 25-byte device identifier |
| 35 | Outer opcode |
| 36 onward | Payload |
| Last two | CRC16/MODBUS, little endian, over bytes 2 through payload |

The app sequence increments in decimal but converts its zero-padded eight digits as hexadecimal pairs (`00000009` → `00000010`). Replies are correlated by both outer and inner sequences: a delayed response in the capture reused a newer outer sequence while retaining its old inner sequence.

1. Subscribe to notifications.
2. Send outer `04`, payload `01 01` + six clock bytes + `03`. A new client starts with an all-zero identifier.
3. Receive outer `01`, learn the identifier, and compare its SHA256 with the stored identity on subsequent sessions.
4. Send outer `02`, payload ASCII `2.0` zero-padded to six bytes + six clock bytes.
5. Send outer `30` / inner `80` to read telemetry; receive outer `31` / inner `80`.

Clock bytes are year minus 2022, month, day, hour, minute, second. The implementation uses HA's configured local timezone. The code does not implement the separate clock-setting command.

Request wrapper is `03` + LE16(inner length) + inner packet. Reply wrapper is `03 00` + LE16(inner length) + inner packet; nonzero status is rejected. Inner magic is `55 AA` for requests and `AA 55` for replies. Inner length excludes the final checksum. The checksum is the sum of preceding inner bytes modulo 65536, little endian. Sequence sits at inner bytes 8–11, command at 13, body begins at 14.

The request reads main register block 13000 (300 bytes), and six expansion summary blocks: 13300/1, 13342/2, 13346/2, 13500/1, 13542/2, 13546/2. Expansion values are currently ignored.

## Exposed fields in block 13000

| Offset | Format | Reading |
|---|---|---|
| 54 | unsigned LE16 ÷10 | Battery V |
| 60 | signed LE16 | Battery °C |
| 62 | unsigned LE16 | Battery % |
| 80 | unsigned LE16 | AC output W |
| 82 | unsigned LE16 ÷10 | USB-A W |
| 84 | unsigned LE16 ÷10 | USB-C W |
| 92 / 93 / 94 | byte, 0 or 1 | AC / DC / USB enabled |

App-style total output = offset 80 + (82 + 84 + 86 + 88 + 260)/10, each term read as unsigned LE16. Nonzero USB/DC readings remain to be validated in real operating modes. Charging, cell voltage and runtime fields are deliberately omitted.

## Output controls

A stock-app capture on October 24, 2026 confirmed on/off commands and subsequent actual-state changes for all three output groups:

| Group | Register | Value |
|---|---|---|
| AC | 42001 | One byte, 0 off / 1 on |
| DC | 42002 | One byte, 0 off / 1 on |
| USB (shared group) | 42003 | One byte, 0 off / 1 on |

The 63-byte request uses outer `30`, inner `85`. Body: block count `01`, register LE16, length `01 00`, boolean byte. The 64-byte acknowledgement uses **outer `33`**, inner `85`, success wrapper `03 00`, and echoes the single register/value. It is not a telemetry response (`31`). Its captured inner header bytes 4–7 are `00 01 00 0A`, with `03` at byte 12. The client validates identity, both sequences, both checksums, status, exact register and value.

An acknowledgement is not sufficient proof of the physical output state. Poll block 13000 and compare offsets 92/93/94 with the requested state, allowing up to 20 seconds with two-second intervals between unsuccessful readbacks. The similarly named fields in settings block 42000 are not used as actual-state confirmation.

All outgoing messages pass a narrow allowlist immediately before transport. The ordinary send path permits only handshake/telemetry; a separate control path permits one boolean write to one of the three registers above. Inner `82` settings queries, `84` bulk settings writes, other `85` registers, outer `32` configuration and firmware commands remain excluded. Protocol tests check refusal even when checksums are valid. Commands are never automatically replayed after ambiguous transport failures, and no commands are sent during setup or reconnect.

The public telemetry fixture uses a fabricated identifier, a fixed timestamp and constructed values. Output request fixtures were generated offline using the app's encoder with a zero identifier. Acknowledgement fixtures preserve the observed response layout but replace the device identifier and sequences and recalculate checksums. No raw phone capture or original device identifier is included.
