# Pion Power Trek for Home Assistant

[![Validation](https://github.com/gmaclean1981/ha-pion-trek/actions/workflows/validate.yml/badge.svg)](https://github.com/gmaclean1981/ha-pion-trek/actions/workflows/validate.yml)
[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gmaclean1981&repository=ha-pion-trek&category=integration)

A community custom integration for **local Bluetooth telemetry, AC/DC/USB output control and charging settings for the Pion Power Trek 4200**. No MQTT broker, FSpower account, cloud connection, separate bridge service or always-on PC is required during operation.

**Version 0.4.0 — settings validated on one Trek 4200.** Adds Minimum discharge and AC charging power limit configuration entities, bringing the device to twenty-eight entities while retaining all twenty-six existing identities. Both controls passed independent Bluetooth and Home Assistant UI trials on October 24, 2026. Actual charging-rate reduction and cutoff at the discharge floor have not been tested.

**Additional settings trial, October 24, 2026:** The Windows client changed the reserve from 3% to 10%, lowered the ordinary AC charging limit from 3000 W to 1000 W, then restored 3000 W. A fresh connection confirmed 10% / 3000 W. Three writes, nine telemetry reads and eight settings reads completed over two BLE connections at MTU 517, with zero invalid frames. On Home Assistant 2026.10.2, the UI then confirmed 10% → 15% → 10% and 3000 W → 1500 W → 3000 W. The local BlueZ session recorded 23 telemetry reads and nine settings reads on one connection, with zero invalid frames. Each write required fresh device confirmation; maximum charge stayed 90%, all other queried setting bytes stayed unchanged, and AC stayed on with DC/USB off. Reloading the HA integration then established a fresh connection and retained 10% minimum discharge, 90% maximum charge and 3000 W AC charging limit; four fresh telemetry reads completed with zero invalid frames. These trials validate setting writes and readback, not a full charging/discharging cycle, power-cycle retention, or writes through an ESPHome proxy. No new stock-app capture was needed for these controls; their registers came from the previously analyzed Android app and settings reads.

**Version 0.3.0** adds a Maximum charge configuration entity and twelve diagnostic entities for device metadata, battery health and internal temperatures. All thirteen entities from 0.2.0 keep their identities; the device now has twenty-six entities. Serial number, hardware version and communications firmware also populate the existing HA device information. Both the direct Bluetooth trial and the Home Assistant UI trial confirmed 85% and restored 90%; all other queried settings and output states stayed unchanged.

**Direct charge-limit trial, October 24, 2026:** Stock-app traffic confirmed a 90% → 85% → 90% change, with only the maximum-charge byte changing in full settings readbacks. A subsequent independent client sent just two single-register writes, confirmed 85%, restored 90%, and read 90% again on a fresh connection. All other queried settings and actual output states stayed unchanged (AC on, DC/USB off). Six telemetry reads and six settings reads completed over two Windows BLE connections at MTU 517, with zero invalid frames. This verifies the setting and its persistence across a BLE reconnect, not a full charging cycle or a power-cycle retention test.

**Local charge-limit UI trial, October 24, 2026:** Installed 0.3.0b2 over 0.3.0b1 on Home Assistant 2026.10.2. The new Maximum charge entity appeared under Configuration and reported the existing 90% value. A keyboard edit to 85% was confirmed in HA history, then a second edit restored 90%. AC stayed on and DC/USB off throughout. The setting service reports success only after the Trek acknowledges the command and fresh settings/output reads pass. The BlueZ connection negotiated MTU 517 and completed 17 telemetry reads plus six settings reads on one connection, with zero invalid frames. Reloading the integration then reconnected successfully and read the retained 90% ceiling. Charge changes through an ESPHome proxy have not yet been separately tested. All twenty-five entities from the local diagnostics build retained their IDs, and the charge control appeared as the twenty-sixth entity on the same device.

**Local diagnostics trial, October 24, 2026:** Installed over 0.2.0 and restarted Home Assistant 2026.10.2. All thirteen existing entity IDs were preserved and twelve diagnostic entities appeared on the same device. Live readings showed 99% battery health and internal temperatures around 37–44 °C; serial and versions matched earlier captures. The local BlueZ connection negotiated MTU 517 and completed 14 successful polls on one connection with zero invalid frames. AC remained on and DC/USB off; no output or charging settings were changed during this trial. The integration's diagnostic download continues to exclude serials, addresses, fingerprints and raw frames. This is a short functional trial; the new metadata has not yet been separately observed through an ESPHome proxy.

**Version 0.2.0, locally validated on Home Assistant 2026.10.2.** Adds three output switches while preserving all ten existing telemetry entities and their identities. Stock-app captures confirmed all six on/off commands, matching acknowledgements and actual output-state changes. This integration then successfully switched DC and USB on and off in live HA tests, with matching telemetry and both restored to off. AC stayed on during the HA tests: its command/response format and physical state changes were validated using the owner's stock-app capture, not another HA interruption. The earlier telemetry validation below describes the previous public release. Output switching through an ESPHome proxy has not yet been separately tested; the live switching trial used HA's local BlueZ adapter.

**Earlier telemetry validation (0.1.1), on Home Assistant 2026.10.2.** One Trek 4200 produced all ten entities through both HA's local BlueZ Bluetooth adapter and a Wyze Outdoor Plug running ESPHome 2026.8.2 with active Bluetooth proxy support. Both paths negotiated MTU 517. The local-adapter trial recorded 28 consecutive successful polls on one connection, no invalid frames, and a successful integration reload/reconnect. The proxy trial verified automatic reconnection from the local adapter to the proxy, fresh telemetry, and continued proxy operation after the local adapter was restored. Other FSpower products, proxy hardware and firmware variants are unconfirmed.

During the proxy observation window, diagnostics increased from 10 to 21 successful polls while the connection count remained at two (the first local session and the subsequent proxy session), with zero invalid frames. This establishes 11 additional successful polls on the same proxy connection; the full counter of 21 includes earlier local polls. These are short functional trials, not long-term reliability testing.

The earlier standalone reader also completed a fresh connection and three successful polls with its PC's network disconnected. This HA trial confirmed local Bluetooth operation; a separate Internet-blocked HA reconnect test has not been performed.

## What it exposes

| Entity | Unit / state |
|---|---|
| Battery | % |
| Battery voltage | V |
| Battery temperature | °C |
| Total output power | W |
| AC output power | W |
| USB-A output power | W |
| USB-C output power | W |
| AC output enabled | On / off status |
| DC output enabled | On / off status |
| USB output enabled | On / off status |
| AC output | On / off control |
| DC output | On / off control |
| USB output | On / off control, shared USB group |
| Maximum charge | Configuration control, whole % |
| Minimum discharge | Configuration control, whole %, below Maximum charge |
| AC charging power limit | Configuration control, W, 100 W steps |
| Serial number | Diagnostic text |
| Hardware version | Diagnostic text |
| Communications firmware | Diagnostic text |
| DSP firmware | Diagnostic text |
| BMS firmware | Diagnostic text |
| Reported software version | Diagnostic text, exact component unknown |
| Battery health | Diagnostic %, device-reported state of health |
| Internal temperature 1–5 | Five diagnostic sensors, °C |

One telemetry request updates the original twenty-five entities every 10 seconds. The twelve metadata/temperature diagnostics add no Bluetooth requests. The three configuration numbers share a fixed settings query on connection and approximately every 60 seconds, plus fresh reads around a requested change. There are twenty-eight entities in total. An unavailable device produces unavailable entities, then polling retries. A new connection verifies the device fingerprint saved during setup. Entity unique IDs remain stable across reloads and software updates.

The five internal temperature locations are not identified by the app, so their numbering is preserved. Battery health is the device's estimate, not an independent capacity test or the present battery charge percentage. The device-info firmware field uses the communications firmware; DSP, BMS and the additional reported software value remain separate sensors. Missing or malformed optional metadata is shown as unknown without discarding valid power and battery readings. A previously learned device-info version is retained until another valid version is received. Serial numbers are available locally in HA but excluded from this integration's diagnostic download; redact screenshots or HA exports before sharing if they include identifying details.

The original three output-status binary sensors remain available for existing automations and history. The new switches set AC, DC and the shared USB output group on or off. USB-A and USB-C cannot be switched separately through these commands.

Switches report the actual telemetry state. A command is sent once, its response is validated, and telemetry is polled for up to 20 seconds to confirm the requested state. Commands and regular polls share one serialized BLE connection. A failed or interrupted command is never automatically replayed; it may already have reached the device. Check the actual state before retrying. No output changes are sent during setup, startup or reconnect.

Maximum charge uses whole-percent steps up to 100%, above the freshly read minimum discharge limit. Minimum discharge uses whole-percent steps from 3 to 90%, below Maximum charge. The 3% lower bound preserves the observed factory setting; the Android editor only offers 10–90%. These are the integration's accepted input ranges, not a claim that every value has been hardware tested. AC charging power limit accepts 100–3000 W in 100 W steps. Zero watts is excluded until its behavior is established. This is the ordinary AC charging inlet's ceiling, separate from the EV/hybrid-port limit; actual input power depends on the supply and operating conditions.

Every configuration change checks fresh settings, writes only the requested register once, validates the acknowledgement, and reads back the result. It also checks that all other queried settings and actual AC/DC/USB states are unchanged. The displayed value comes from the device, with no optimistic update. An already-current value causes no write. Failed or interrupted writes are never automatically replayed; check the current setting before retrying. Setup, restart and reconnect only read the settings.

Other charging settings, main device shutdown, firmware updates and arbitrary commands are not exposed. Handshake packets include the local clock, as the app does; there is no separate clock-setting command.

Total output uses the same six-output sum as the app. Basic battery/AC readings were checked against the live display. Nonzero USB/DC loads and all operating modes still need validation. Charging/input power, remaining runtime, cell voltages, expansion batteries, and energy totals are omitted because their meanings/scales or operating modes have not been sufficiently verified.

## Requirements

- Home Assistant **2026.10 or newer** with the Bluetooth integration.
- A supported local Bluetooth adapter **or an ESPHome Bluetooth proxy with active connections enabled**, in range of the Trek. A passive advertisement-only proxy is insufficient.
- A free Bluetooth connection slot. The integration holds one active connection while loaded.
- Close FSpower on all phones while the integration is connected. The Trek may allow only one app/client connection. Disable this integration temporarily when you want to use FSpower again.

HA selects a connectable adapter/proxy; there is no hard-coded adapter address and the integration does not start its own scanner. An ESPHome proxy needs **local LAN access to HA**, but no Internet access for telemetry. Internet access is normally needed to download/install the integration and dependencies.

For proxy verification, use **Settings → Connectivity → Bluetooth → Connections** to identify the adapter carrying the Trek's active connection. The advertisement monitor can show the preferred source rather than every scanner that hears the Trek. This integration does not pin a particular proxy. In HA 2026.10.2, its diagnostic backend label can appear as `partial` for a proxy; the connection monitor identifies the actual proxy.

## Install using HACS

Repository: **https://github.com/gmaclean1981/ha-pion-trek**. Use the **Open in HACS** button above, or follow these steps:

1. In HACS, open **Custom repositories** and add the repository URL, category **Integration**.
2. Download **Pion Power Trek**, then restart Home Assistant.
3. Under **Settings → Devices & services**, confirm a discovered Trek. Or choose **Add integration → Pion Power Trek** and select its Bluetooth address.
4. Close FSpower on all phones, then submit the setup screen. A live read must succeed before the entry is saved.

HACS default-catalogue inclusion is a separate process and is not required for a custom repository.

Already installed manually? Add this custom repository and download the release through HACS to let HACS manage future updates. Keep your existing Trek integration entry; there is no need to add the device again.

### Manual installation / first trial

1. Copy `custom_components/pion_trek` into `/config/custom_components/pion_trek` on HA. Keep the whole folder, including translations and brand assets.
2. Restart HA and add **Pion Power Trek** as above.
3. Check the battery percentage and AC/total output against the Trek display. Verify that ordinary readings update.
4. For a cloud-independence test, block Internet access while keeping HA-to-proxy LAN connectivity. Reconnect/reload the integration and confirm fresh readings. The earlier offline test covered the standalone reader, not this HA deployment.

Do not run the standalone reader and this integration simultaneously. No phone app or APK extraction is needed for normal installation.

## Troubleshooting

- **No discovery:** close the phone apps and check HA's Bluetooth advertisement monitor. Devices with a `TM` name and service `000000ff-0000-1000-8000-00805f9b34fb` are offered as candidates, not assumed to be supported. You can enter the Trek's address manually.
- **Cannot connect:** check range, proxy active-connection support and available slots. A reader on another computer may still hold the connection.
- **MTU error:** this protocol sends an 86-byte read request and requires negotiated MTU ≥89. Version 0.1.1 acquires the real BlueZ MTU before checking it, using [Bleak's documented workaround](https://github.com/hbldh/bleak/blob/v3.0.2/examples/mtu_size.py); BlueZ otherwise reports a default of 23. A genuinely small MTU still prevents setup. Try another supported adapter or an active proxy. Arbitrary fragmentation has not been validated.
- **Unsupported device:** a live reply did not match the tested protocol. Other FSpower models are not assumed compatible merely because they advertise the same service.
- **Unavailable readings:** check the above; the integration disconnects failed sessions and retries with a fresh client. It does not retain stale readings as available.
- **Diagnostics:** download diagnostics from the integration menu. They contain connection status, counters and negotiated MTU, without serial numbers, Bluetooth addresses, fingerprints or raw frames.
- **Phone app access:** disable the integration to release Bluetooth, then open FSpower. Close the app before re-enabling it.

Removal: delete the integration entry, then remove its files using HACS or delete its custom-component folder and restart HA. No changes to Trek firmware need undoing.

## Development

Validation on October 24, 2026: **358 test cases passed** across the full development suite and subsequent targeted runs on Home Assistant 2026.10.2 / Python 3.14.9, with network sockets disabled and BLE mocked. Coverage includes the real HA setup flow and entity platforms, retry/unavailable behavior, entity IDs across reloads, connection cleanup, packet integrity, the outgoing command allowlists and BlueZ MTU acquisition. Output tests additionally cover all six commands, captured acknowledgements, delayed or missing state changes, rejected/mismatched replies, ambiguous failures without replay, cancellation, serialized polling and real HA switch services. Ruff lint/format checks passed. The six encoded commands matched the stock-app capture byte-for-byte; original identifying data and raw captures are not shipped. Metadata tests cover optional fields, version formatting, diagnostic categories, device-registry updates and stable identities. Charging tests cover the fixed settings query, intent-bound single-register gates, fresh minimum/maximum checks, exact one-/two-byte comparison masks, unchanged outputs, delayed/failed acknowledgements, cancellation, no replay, invalid ranges/steps, unavailable recovery and the real HA number services. Five live charging-exchange fixtures use the verified acknowledgement layout with identifying data replaced. The live HA trials described above complement the automated tests. See the validation badge for the current GitHub Actions results, including hassfest and HACS validation.

`python -m pip install -r requirements-dev.txt` then `pytest` runs protocol, transport and HA integration tests. Use Linux and the Python version required by the pinned HA test harness. Tests use a fake BLE transport; they do not connect to devices or operate outputs. Run `ruff check .` and `ruff format --check .` for style checks. GitHub Actions also runs hassfest.

Only original integration code and privacy-safe protocol fixtures belong in this repository. Telemetry/request fixtures are synthetic; output acknowledgements and the five live charging-setting exchanges are capture-derived with fabricated identifiers and fixed sequences; settings-read fixture values are synthetic. The extracted app, phone bugreport, raw Bluetooth captures, private device address/identifier, and research tools are not included.

Protocol notes are in [PROTOCOL.md](PROTOCOL.md). Support is presently scoped to the tested Trek 4200. This is an independent community project, not an official Pion Power or FSpower product.

References: [HA Bluetooth integration development](https://contributors.home-assistant.io/core/integrations/bluetooth/), [ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy/), [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/).
