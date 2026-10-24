# Changelog

## 0.3.0 — 2026-10-24

- Twelve diagnostic entities: serial number, hardware version, communications/DSP/BMS firmware, an additional reported software version, battery health, and five internal temperatures. Serial, hardware and communications firmware also populate HA's device information.
- Maximum charge configuration control in whole-percent steps, above the device's minimum discharge limit and up to 100%. The device's existing limit is read at startup; no setting is reapplied on reconnect.
- A fixed settings query and a write restricted to the maximum-charge register. Each change requires acknowledgement, fresh settings readback, and checks that other queried settings and AC/DC/USB states are unchanged. Ambiguous writes are never automatically replayed.
- Existing entity identities preserved. The thirteen entities from 0.2.0 become twenty-six; installations of the local diagnostics/charge betas retain their existing entities too.
- Settings-read counters in diagnostics. Serial numbers remain available locally but are excluded from the integration's diagnostic download, along with addresses, fingerprints and raw frames.

All 265 test cases and Ruff checks passed during development. Live tests on Home Assistant 2026.10.2 confirmed 90% → 85% → 90% and read 90% again after reloading, with AC on and DC/USB off throughout. Metadata and temperatures matched prior captures. Charge writes were tested using HA's local Bluetooth adapter; writes through an ESPHome proxy, full charge-cycle behavior and power-cycle retention remain untested. Temperature locations and the component represented by the additional software-version field remain unidentified. Battery health is the device's estimate.

Update through HACS and restart Home Assistant. Keep the existing integration entry; no re-pairing or entity migration is required.

## 0.2.0 — 2026-10-24

- AC, DC and shared USB output switches with acknowledged writes and actual telemetry confirmation.
- Existing ten sensor identities and history preserved; three new switch entities added.
- Serialized polling and switching, bounded confirmation, and no automatic replay after failed commands.
- Strict command/response validation based on all six stock-app actions captured on a Trek 4200.
- Additional tests for delayed state changes, rejected/mismatched responses, ambiguous failures, cancellation, concurrent reads and Home Assistant switch services.

All 125 automated tests and Ruff checks passed. Live HA tests confirmed DC and USB on/off and restored both to off. AC was left on during HA testing; its on/off packets, acknowledgements and actual state transitions were validated from the owner's stock-app capture. Existing telemetry remains live. This release also corrects diagnostics to read the installed manifest version instead of a hard-coded label.

## 0.1.1 — 2026-10-24

First public release: local, read-only Bluetooth telemetry for the Pion Power Trek 4200.

- Ten Home Assistant entities for battery percentage, voltage, temperature, total/AC/USB-A/USB-C output power, and AC/DC/USB enabled status.
- Bluetooth discovery and manual setup, with a successful live telemetry read required before saving the device.
- One shared telemetry poll every ten seconds, connection recovery, stable entity identities and connection diagnostics.
- Support for Home Assistant Bluetooth routing through local adapters and active ESPHome proxies.
- Linux BlueZ MTU acquisition before checking packet-size compatibility; genuinely insufficient MTUs remain rejected.
- An outgoing command allowlist that permits only the observed session handshake and telemetry requests.

Validated on Home Assistant 2026.10.2 with one Trek 4200, both a local Bluetooth adapter and a Wyze Outdoor Plug running ESPHome 2026.8.2. Forty automated tests cover protocol checks, the HA setup/entity lifecycle, failure recovery and MTU handling.

This is an early release. Other FSpower models, nonzero USB/DC loads and long-term reliability remain unverified. Charging/input power, remaining runtime, cell voltages, expansion batteries and output/charging controls are not exposed. See the README for the precise offline and hardware test scope.
