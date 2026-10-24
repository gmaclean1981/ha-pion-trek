# Pion Power Trek for Home Assistant

[![Validation](https://github.com/gmaclean1981/ha-pion-trek/actions/workflows/validate.yml/badge.svg)](https://github.com/gmaclean1981/ha-pion-trek/actions/workflows/validate.yml)
[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gmaclean1981&repository=ha-pion-trek&category=integration)

A community custom integration for **local, read-only Bluetooth telemetry from the Pion Power Trek 4200**. No MQTT broker, FSpower account, cloud connection, separate bridge service or always-on PC is required during operation.

**Status: 0.1.1 prototype, tested locally on Home Assistant 2026.10.2.** One Trek 4200 produced all ten entities through both HA's local BlueZ Bluetooth adapter and a Wyze Outdoor Plug running ESPHome 2026.8.2 with active Bluetooth proxy support. Both paths negotiated MTU 517. The local-adapter trial recorded 28 consecutive successful polls on one connection, no invalid frames, and a successful integration reload/reconnect. The proxy trial verified automatic reconnection from the local adapter to the proxy, fresh telemetry, and continued proxy operation after the local adapter was restored. Other FSpower products, proxy hardware and firmware variants are unconfirmed.

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

One telemetry request updates all ten entities every 10 seconds. An unavailable device produces unavailable entities, then polling retries. A new connection verifies the device fingerprint saved during setup. Entity unique IDs remain stable across reloads and software updates.

The three output entities are **binary sensors**. This version cannot turn outlets on/off, change charging settings, update firmware or send arbitrary commands. BLE writes are still needed for the stock-app session handshake and telemetry requests. Handshake packets include the local clock, as the app does; there is no separate clock-setting command.

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

Validation on October 24, 2026: **40 tests passed** on Home Assistant 2026.10.2 / Python 3.14.9, with network sockets disabled and BLE mocked. Coverage includes the real HA setup flow and entity platforms, retry/unavailable behavior, entity IDs across reloads, connection cleanup, packet integrity, the outgoing command allowlist and BlueZ MTU acquisition (including genuinely small MTUs and acquisition failures). Ruff lint/format checks passed. The public decoder also agreed with all seven original captured telemetry replies in a private local cross-check; original captures are not shipped. The live HA trial described above followed these tests. See the validation badge for GitHub Actions results, including hassfest and HACS validation.

`python -m pip install -r requirements-dev.txt` then `pytest` runs protocol, transport and HA integration tests. Use Linux and the Python version required by the pinned HA test harness. Tests use a fake BLE transport; they do not connect to devices or operate outputs. Run `ruff check .` and `ruff format --check .` for style checks. GitHub Actions also runs hassfest.

Only original integration code and synthetic protocol fixtures belong in this repository. The extracted app, phone bugreport, Bluetooth captures, private device address/identifier, and research tools are not included.

Protocol notes are in [PROTOCOL.md](PROTOCOL.md). Support is presently scoped to the tested Trek 4200. This is an independent community project, not an official Pion Power or FSpower product.

References: [HA Bluetooth integration development](https://contributors.home-assistant.io/core/integrations/bluetooth/), [ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy/), [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/).
