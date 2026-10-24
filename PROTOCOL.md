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
| 1–25 | ASCII, matching outer identifier | Serial number |
| 54 | unsigned LE16 ÷10 | Battery V |
| 60 | signed LE16 | Battery °C |
| 62 | unsigned LE16 | Battery % |
| 64 | unsigned LE16 | Battery health %, device estimate |
| 80 | unsigned LE16 | AC output W |
| 82 | unsigned LE16 ÷10 | USB-A W |
| 84 | unsigned LE16 ÷10 | USB-C W |
| 92 / 93 / 94 | byte, 0 or 1 | AC / DC / USB enabled |
| 145–149 | Five unsigned bytes | Internal temperatures 1–5, °C |
| 152–155 | Four decimal bytes, dot-separated | Reported software version; component not established |
| 156–159 | Four decimal bytes, dot-separated | Hardware version |
| 160–161 | Two **hexadecimal** bytes, dot-separated | DSP firmware |
| 269–272 | Four decimal bytes, dot-separated | Communications firmware (app's DebugSoftVer / Mater_Com) |
| 273–280 | NUL-padded ASCII | BMS firmware |

App-style total output = offset 80 + (82 + 84 + 86 + 88 + 260)/10, each term read as unsigned LE16. Nonzero USB/DC readings remain to be validated in real operating modes. Charging, cell voltage and runtime fields are deliberately omitted.

Metadata offsets and formatting were compared with the app parser and 25 captured telemetry responses from two sessions. All five temperature locations remain unidentified. Versions consisting entirely of zero or FF bytes, invalid/nonmatching serial text, invalid BMS text, battery health above 100, and temperature FF bytes are treated as unknown. Suppressing FF temperatures is a conservative validity rule, not a confirmed vendor sentinel definition. Zero degrees and zero-percent health remain representable. Metadata never changes entity identity or the permitted outgoing commands.

## Maximum battery charge

Settings read: outer `30`, inner `82`. The fixed query requests 42000/100, 45668/2, 45674/2, 45678/1, 45673/1, 45680/1 and 45670/2. Reply: outer `33`, inner `82`. Both sequences, identity, checksums, status and exact block sizes are checked before accepting settings.

Main block 42000 has one-byte maximum state of charge at offset 59 (register **42059**, LE bytes `4B A4`), minimum discharge state of charge at offset 60, and maximum charging-current percentage at offset 61. They are distinct settings. An earlier captured reply reported 90%, 3% and 100% respectively.

The stock app uses outer `32`, inner `84` for a bulk write of eighteen settings. The integration instead permits exactly one register: body `01 4B A4 01 00 <percentage>`. The number accepts whole percentages above the freshly read minimum discharge limit and at most 100. It never writes that minimum, charging-current percentage, other settings or output switches through this path. On October 24, 2026, the single-register request was accepted twice (85%, then 90%) and each result was independently read back. Its 64-byte acknowledgement uses outer `33`, inner `84`, status `00`, and echoes the one-register body. Both sequences, identity, checksums, header and exact register/value are validated. The client then reconnected and read 90% again. The stock-app capture independently showed both transitions and matching bulk acknowledgements, with only byte 59 changing in the queried settings. No output commands were sent in this trial.

Each charge change is serialized with all other BLE operations: fresh settings read, actual output-state baseline, one write, acknowledgement validation, fresh settings readback and output-state check. All other queried settings bytes must match the baseline before success is reported. A request for the current value performs no write. Failures disconnect and are never replayed; subsequent reads reconcile the device's actual setting. Normal settings refresh is approximately 60 seconds and on every new connection. Startup/reconnect never restores or reapplies a saved charge value.

## Additional charging controls in 0.4.0

The app maps minimum discharge SOC to register **42060** (one byte) and ordinary AC charging power to **45668** (two-byte little-endian watts). Their previously captured values were 3% and 3000 W. Both are present in the existing settings query. On October 24, 2026, the independent client successfully changed the reserve to 10% and the AC limit from 3000 W to 1000 W, then restored 3000 W. Each command received a matching acknowledgement and fresh readback. A new BLE connection read the retained 10% / 3000 W values. Maximum charge stayed 90%, every other queried setting stayed unchanged, and AC remained on with DC/USB off. Three identifier-sanitized request/reply pairs from that client trial are included in the tests. No new stock-app change capture was collected for these two controls.

The integration sends one outer `32` / inner `84` block: `01 4C A4 01 00 <percent>` or `01 64 B2 02 00 <watts LE16>`. Every outgoing gate is bound to the intended setting, width, range and step; an otherwise valid command for another supported setting is rejected. Acknowledgements must echo the exact register and value. Readback comparison masks only the selected one or two bytes; maximum charge, the other charging control, hybrid-port settings and output states must remain unchanged. The minimum must be below a freshly read maximum, and the maximum above the fresh minimum. Unsupported AC-power values are represented as unknown without discarding other valid readings.

The integration permits a 3–90% reserve and 100–3000 W in 100 W steps. The Android UI offers 10–90% and 0–3000 W; the integration preserves the known 3% baseline and excludes zero-watt writes until their behavior is established. These are software validation bounds, not proof of hardware acceptance of every value. Actual charging-power reduction under load, cutoff at the discharge floor, proxy writes and power-cycle retention remain untested.

## Output controls (validated in 0.2.0)

A stock-app capture on October 24, 2026 confirmed on/off commands and subsequent actual-state changes for all three output groups:

| Group | Register | Value |
|---|---|---|
| AC | 42001 | One byte, 0 off / 1 on |
| DC | 42002 | One byte, 0 off / 1 on |
| USB (shared group) | 42003 | One byte, 0 off / 1 on |

The 63-byte request uses outer `30`, inner `85`. Body: block count `01`, register LE16, length `01 00`, boolean byte. The 64-byte acknowledgement uses **outer `33`**, inner `85`, success wrapper `03 00`, and echoes the single register/value. It is not a telemetry response (`31`). Its captured inner header bytes 4–7 are `00 01 00 0A`, with `03` at byte 12. The client validates identity, both sequences, both checksums, status, exact register and value.

An acknowledgement is not sufficient proof of the physical output state. Poll block 13000 and compare offsets 92/93/94 with the requested state, allowing up to 20 seconds with two-second intervals between unsuccessful readbacks. The similarly named fields in settings block 42000 are not used as actual-state confirmation.

All outgoing messages pass a narrow allowlist immediately before transport. The ordinary send path permits only handshake/telemetry; a separate control path permits one boolean write to one of the three registers above. Separate paths allow only the fixed inner `82` settings query and a single outer `32` / inner `84` write to the specifically requested charging setting (42059, 42060 or 45668). Bulk settings writes, other `84`/`85` registers, firmware commands and arbitrary configuration remain excluded. Protocol tests check refusal even when checksums are valid. Commands are never automatically replayed after ambiguous transport failures, and no output or charging-setting writes are sent during setup or reconnect.

The public telemetry fixture uses a fabricated identifier, a fixed timestamp and constructed values. Output request fixtures were generated offline using the app's encoder with a zero identifier. Acknowledgement fixtures preserve the observed response layout but replace the device identifier and sequences and recalculate checksums. The live single-register charge requests and acknowledgements are similarly sanitized. Settings-read fixtures contain constructed values rather than the private settings block. No raw phone capture or original device identifier is included.
