# CLAUDE.md — Pion Power Trek for Home Assistant

Context for AI agents working on this repository. Read this first, then README.md (per-version validation log), PROTOCOL.md (reverse-engineered protocol) and CHANGELOG.md.

## What this is

A HACS custom integration (`pion_trek`) that gives Home Assistant local Bluetooth LE access to a **Pion Power Trek 4200** power station. Before this, the Trek was only reachable through the FSpower phone app (`com.hipower.hems`). The protocol was recovered from FSpower Android 1.0.5, passive BLE captures on the owner's unit, and an independent client. No cloud, account, MQTT broker or bridge is used.

The owner directs development and performs all live hardware testing on one Trek 4200 running Home Assistant 2026.10+ (local BlueZ adapter; an ESPHome Bluetooth proxy has also been tested for reads). Earlier versions were coded with Codex; see the AI disclosure in README.md.

## Layout

```
custom_components/pion_trek/
  __init__.py        setup/unload, platforms
  const.py           DOMAIN, MODEL, POLL_INTERVAL (10 s), CONF_FINGERPRINT
  protocol.py        outer/inner framing, CRCs, handshake, telemetry (block 13000) decode,
                     output commands, send allowlists
  charge_protocol.py settings query/decode (block 42000 etc.), single-register setting writes
  client.py          TrekClient: one persistent BLE session, serialized ops, confirm-by-readback
  coordinator.py     DataUpdateCoordinator; HA Bluetooth routing via bleak-retry-connector
  config_flow.py     Bluetooth discovery ("TM" name + service 0xFF) or manual address;
                     a live read must succeed before the entry is created
  entity.py          unique_id = f"{fingerprint}_{key}", shared DeviceInfo
  sensor.py / binary_sensor.py / switch.py / number.py   entity platforms
  diagnostics.py     counters, MTU, backend; no identifying data
  strings.json + translations/en.json   keep in sync
tests/               pytest + pytest-homeassistant-custom-component, fake BLE transport
```

## Protocol essentials (details in PROTOCOL.md)

- Service `000000ff-…`, one write/notify characteristic `0000ff01-…`. Writes **with response**; subscribe before the handshake. Requires negotiated MTU ≥ 89 (BlueZ needs the `_acquire_mtu()` workaround in `client.py`).
- Outer frame: `A5 5A`, LE16 length, 4-byte sequence, 25-byte device identifier, opcode, payload, CRC16/MODBUS. Inner packet: `55 AA` request / `AA 55` reply, sum-mod-65536 checksum.
- Session: hello (outer `04`) → identifier reply (outer `01`) → platform (outer `02`) → telemetry (`30`/`80` → `31`/`80`). The SHA-256 of the identifier is stored at setup and verified on every new connection.
- Replies are matched on **both** outer and inner sequence (a delayed reply can reuse a newer outer sequence).
- Telemetry: register block 13000 drives all sensors and the actual output states (offsets 92/93/94). Settings: inner `82` query, read on connect and about every 60 s.

## Non-negotiable design rules

Keep these when changing anything. The owner relies on them.

1. **Narrow outgoing allowlists.** Each send path validates the frame just before transport. The only writes allowed are:
   - one boolean to output registers 42001 (AC), 42002 (DC) or 42003 (USB group), outer `30` / inner `85`;
   - one value to 42059 (max charge %), 42060 (min discharge %) or 45668 (AC charge power W, LE16), outer `32` / inner `84`.
   No bulk settings writes (the app's 18-setting write), no firmware or arbitrary commands, no clock-setting command. Any new command needs its own bound validator and tests proving that other valid-checksum frames are refused.
2. **Confirm, don't assume.** Validate the acknowledgement exactly (identity, both sequences, both checksums, status, register, value), then confirm with a fresh read (outputs: telemetry, up to 20 s at 2 s intervals; settings: fresh settings read). For settings changes, also check that every other queried setting and the AC/DC/USB states are unchanged.
3. **No optimistic state.** Entities show only what the device reported. On failure, mark data unavailable until the next normal poll.
4. **Never replay.** A failed or cancelled write may already have reached the device. Disconnect, raise, and let polling reconcile. Don't retry writes automatically.
5. **No writes on setup, startup or reconnect.** Only reads.
6. **Already-current value means no write.**
7. **Cross-limit checks.** Max charge must be above a freshly read min discharge, and the reverse.
8. **One serialized connection.** All polls and commands share the client lock and coordinator `_operation_lock`.
9. **Stable entity identities.** Never change an existing entity `key` or unique ID. Every release so far has verified that all prior IDs are preserved (now 42 entities).
10. **Privacy.** No serial numbers, BLE addresses, raw identifiers, fingerprints or raw frames in logs, diagnostics, fixtures or the repo. Fixtures are synthetic or capture-derived with fabricated identifiers and recomputed checksums. Don't commit the APK, bugreports, raw captures or research tools.
11. **Unknown is not zero.** Malformed or all-FF optional fields become unknown without discarding valid readings. Zero stays a valid value.

## Known quirks (confirmed on hardware)

- **AC input power** (GridActivePwr) is charging-path input, not total wall draw. It reads 0 W during mains passthrough even with about 4 A of AC input current. Don't replace it with V × A or present it as a wall-power meter.
- **Charging status** uses the app's register-parser mapping: 0 idle, 1 charging, 2 discharging. During passthrough the device reports code 2 ("discharging"). The raw code is exposed as the `reported_code` attribute. Don't infer status from current, and don't flip the numeric signs.
- **Battery power/current are signed:** positive means discharging, negative means charging.
- USB-A and USB-C share one output switch (register 42003).
- The five internal temperature locations are unidentified. Keep the numbering.
- The Trek may allow only one BLE client. FSpower must be closed, or the integration disabled, to use the app.

## Not yet validated

Nonzero DC port loads (barrel/RV/car socket); output and setting writes through an ESPHome proxy; actual cutoff at the discharge floor; charging-rate reduction under the AC power limit; settings retention across a power cycle; meter-calibrated accuracy; other FSpower models. Don't claim these work without a documented trial.

## Development workflow

- Install: `python -m pip install -r requirements-dev.txt` (Linux, Python 3.14, matching the pinned HA test harness).
- Test: `pytest --disable-socket --allow-unix-socket`. Lint: `ruff check .` and `ruff format --check .` (line length 100).
- CI (`.github/workflows/validate.yml`): pytest + ruff, hassfest, HACS validation.
- Releases: a feature branch (`release-x.y.z…`) and PR into `main`. Bump `manifest.json` version; owner installs `x.y.zbN` betas locally for hardware trials before release. Update README (version summary + dated trial notes), CHANGELOG and PROTOCOL.md as relevant.
- Documentation style: state exactly what was tested (dates, counts, observed values) and what was **not**. Avoid overclaiming.
- On Windows, clone to a short path with `git -c core.longpaths=true clone …` to avoid "Filename too long".

## Live installation

The owner's HA has one config entry titled "Trek 4200" with entities named `*.trek_4200_*` (sensors, binary sensors, three output switches, three configuration numbers). Sending commands to the live device (switches, numbers) changes real hardware. Ask the owner before doing it, and restore the original values afterwards. Typical baseline: AC output on, DC/USB off, max charge 90%, min discharge 10%, AC charging limit 3000 W.
