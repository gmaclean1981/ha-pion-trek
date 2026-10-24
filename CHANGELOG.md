# Changelog

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
