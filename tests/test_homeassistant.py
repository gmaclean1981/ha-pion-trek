"""Real HA config flows/platforms with synthetic BLE transport."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pion_trek.client import TrekClient
from custom_components.pion_trek.const import CONF_FINGERPRINT, DOMAIN
from custom_components.pion_trek.diagnostics import async_get_config_entry_diagnostics

from .helpers import ADDRESS, CLOCK, FINGERPRINT, SERIAL, FakeBleak


@pytest.fixture
def transport(monkeypatch, mock_bluetooth):
    state = SimpleNamespace(clients=[], peripherals=[], fail=False)

    def factory(hass, address, expected_fingerprint=None):
        async def connect():
            peripheral = FakeBleak(fail_read=state.fail)
            state.peripherals.append(peripheral)
            return peripheral

        client = TrekClient(connect, lambda: CLOCK, expected_fingerprint)
        state.clients.append(client)
        return client

    monkeypatch.setattr("custom_components.pion_trek.coordinator.create_client", factory)
    monkeypatch.setattr("custom_components.pion_trek.config_flow.create_client", factory)
    monkeypatch.setattr(
        "homeassistant.components.bluetooth.async_discovered_service_info", lambda *a, **kw: []
    )
    return state


def entry_for(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Trek 4200",
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_FINGERPRINT: FINGERPRINT},
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_setup_flow_probes_then_releases(hass, transport, monkeypatch):
    # Test config flow independently of starting the entry afterwards.
    monkeypatch.setattr(
        "custom_components.pion_trek.async_setup_entry", AsyncMock(return_value=True)
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS.lower()}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_FINGERPRINT: FINGERPRINT}
    assert transport.peripherals[0].disconnected
    await hass.async_block_till_done()


async def test_user_invalid_address_and_connection_error(hass, transport):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "not a MAC"}
    )
    assert result["errors"] == {CONF_ADDRESS: "invalid_address"}
    assert not transport.clients
    transport.fail = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert transport.peripherals[0].disconnected


async def test_duplicate_not_probed(hass, transport):
    entry_for(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert not transport.clients


async def test_bluetooth_discovery_waits_for_confirmation(hass, transport, monkeypatch):
    monkeypatch.setattr(
        "custom_components.pion_trek.async_setup_entry", AsyncMock(return_value=True)
    )
    info = SimpleNamespace(address=ADDRESS, name="TM-Test")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "bluetooth"}, data=info
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert not transport.clients
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert transport.peripherals[0].disconnected
    await hass.async_block_till_done()


async def test_generic_service_does_not_claim_unrelated_device(hass, transport):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "bluetooth"},
        data=SimpleNamespace(address=ADDRESS, name="Unrelated ESP32"),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "not_supported"
    assert not transport.clients


async def test_entities_failure_recovery_diagnostics_and_unload(hass, transport, entity_registry):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    states = hass.states.async_all()
    trek = [
        s
        for s in states
        if s.entity_id.startswith(("sensor.trek_4200_", "binary_sensor.trek_4200_"))
    ]
    assert len(trek) == 22
    assert hass.states.get("sensor.trek_4200_battery").state == "89"
    assert hass.states.get("sensor.trek_4200_total_output_power").state == "381.0"
    assert hass.states.get("binary_sensor.trek_4200_ac_output_enabled").state == "on"
    assert hass.states.get("binary_sensor.trek_4200_dc_output_enabled").state == "off"
    assert len([s for s in states if s.entity_id.startswith("switch.trek_4200_")]) == 3
    assert hass.states.get("switch.trek_4200_ac_output").state == "on"
    assert hass.states.get("switch.trek_4200_dc_output").state == "off"
    ids_before = {
        e.entity_id: e.unique_id
        for e in entity_registry.entities.values()
        if e.config_entry_id == entry.entry_id
    }

    coordinator = entry.runtime_data
    transport.peripherals[-1].fail_read = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert all(hass.states.get(s.entity_id).state == STATE_UNAVAILABLE for s in trek)
    assert transport.peripherals[0].disconnected
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.trek_4200_battery").state == "89"
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostic["integration_version"] == "0.3.0"
    assert diagnostic["successful_polls"] == 2
    assert diagnostic["connections"] == 2
    assert ADDRESS not in json.dumps(diagnostic)
    assert FINGERPRINT not in json.dumps(diagnostic)
    assert SERIAL not in json.dumps(diagnostic)

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert transport.peripherals[-1].disconnected
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ids_after = {
        e.entity_id: e.unique_id
        for e in entity_registry.entities.values()
        if e.config_entry_id == entry.entry_id
    }
    assert ids_after == ids_before
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_failed_initial_setup_is_retried_and_cleans_up(hass, transport):
    transport.fail = True
    entry = entry_for(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state == ConfigEntryState.SETUP_RETRY
    assert transport.peripherals[0].disconnected


@pytest.mark.parametrize("output", ["ac", "dc", "usb"])
async def test_output_services_confirm_state_and_preserve_other_outputs(hass, transport, output):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    peripheral = transport.peripherals[-1]
    before = dict(peripheral.output_states)
    target = not before[output]
    await hass.services.async_call(
        "switch",
        "turn_on" if target else "turn_off",
        {"entity_id": f"switch.trek_4200_{output}_output"},
        blocking=True,
    )
    assert peripheral.output_states == {**before, output: target}
    state = "on" if target else "off"
    assert hass.states.get(f"switch.trek_4200_{output}_output").state == state
    assert hass.states.get(f"binary_sensor.trek_4200_{output}_output_enabled").state == state
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_failed_output_service_marks_unknown_until_poll_reconciles(hass, transport):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    transport.peripherals[-1].control_mode = "reject"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.trek_4200_dc_output"}, blocking=True
        )
    assert hass.states.get("switch.trek_4200_dc_output").state == STATE_UNAVAILABLE
    await entry.runtime_data.async_refresh()
    assert hass.states.get("switch.trek_4200_dc_output").state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_physical_state_changes_update_switches_on_poll(hass, transport):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    transport.peripherals[-1].output_states["usb"] = True
    await entry.runtime_data.async_refresh()
    assert hass.states.get("switch.trek_4200_usb_output").state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_ha_bluetooth_lookup_routes_connection(hass, monkeypatch):
    from custom_components.pion_trek.coordinator import create_client

    lookups = []
    device = SimpleNamespace(address=ADDRESS)

    def lookup(hass, address, *, connectable):
        lookups.append((address, connectable))
        return device

    monkeypatch.setattr("homeassistant.components.bluetooth.async_ble_device_from_address", lookup)
    peripheral = FakeBleak()
    establish = AsyncMock(return_value=peripheral)
    monkeypatch.setattr("custom_components.pion_trek.coordinator.establish_connection", establish)
    client = create_client(hass, ADDRESS, FINGERPRINT)
    assert (await client.async_poll()).battery_level == 89
    assert lookups == [(ADDRESS, True)]
    assert establish.call_args.args[1] is device
    assert establish.call_args.kwargs["ble_device_callback"]() is device
    await client.async_close()


async def test_diagnostic_entities_and_existing_device_upgrade(
    hass, transport, entity_registry, device_registry
):
    from custom_components.pion_trek.charge_protocol import validate_settings_query
    from custom_components.pion_trek.protocol import validate_tx

    entry = entry_for(hass)
    existing_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FINGERPRINT)},
        name="Trek 4200",
        manufacturer="Pion Power",
        model="Trek 4200",
    )
    existing_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{FINGERPRINT}_battery_level",
        suggested_object_id="my_existing_trek_battery",
        config_entry=entry,
        device_id=existing_device.id,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(existing_entity.entity_id).state == "89"
    device = device_registry.async_get_device_by_identifier((DOMAIN, FINGERPRINT), entry.entry_id)
    assert device.id == existing_device.id
    assert device.serial_number == SERIAL
    assert device.hw_version == "0.0.2.3"
    assert device.sw_version == "1.2.3.4"
    expected = {
        "serial_number": SERIAL,
        "hardware_version": "0.0.2.3",
        "communications_firmware": "1.2.3.4",
        "dsp_firmware": "01.1a",
        "bms_firmware": "V9.87",
        "reported_software_version": "0.0.0.9",
        "battery_health": "97",
        **{f"internal_temperature_{i}": str(30 + i) for i in range(1, 6)},
    }
    entries = [e for e in entity_registry.entities.values() if e.config_entry_id == entry.entry_id]
    assert len(entries) == 26
    assert {e.device_id for e in entries} == {device.id}
    assert sum(e.entity_category == EntityCategory.DIAGNOSTIC for e in entries) == 12
    for key, value in expected.items():
        entity_id = f"sensor.trek_4200_{key}"
        state = hass.states.get(entity_id)
        assert state.state == value
        assert entity_registry.async_get(entity_id).entity_category == EntityCategory.DIAGNOSTIC
        if key.startswith("internal_temperature"):
            assert state.attributes["device_class"] == "temperature"
            assert state.attributes["unit_of_measurement"] == "°C"
        elif key == "battery_health":
            assert state.attributes["unit_of_measurement"] == "%"
            assert "device_class" not in state.attributes  # Not state of charge.
        else:
            assert "state_class" not in state.attributes
            assert "unit_of_measurement" not in state.attributes
    # Adding twelve entities must not add extra reads or any settings writes.
    assert entry.runtime_data.client.poll_count == 1
    for frame in transport.peripherals[-1].writes:
        if frame[35] == 0x30 and frame[52] == 0x82:
            validate_settings_query(frame)
        else:
            validate_tx(frame)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_metadata_refresh_updates_device_without_erasing_known_versions(
    hass, transport, device_registry
):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    original_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, FINGERPRINT), entry.entry_id
    )
    peripheral = transport.peripherals[-1]
    peripheral.metadata_overrides = {269: bytes([1, 2, 3, 5]), 145: bytes([40])}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    device = device_registry.async_get(original_device.id)
    assert device.sw_version == "1.2.3.5"
    assert hass.states.get("sensor.trek_4200_communications_firmware").state == "1.2.3.5"
    assert hass.states.get("sensor.trek_4200_internal_temperature_1").state == "40"

    peripheral.metadata_overrides = {269: bytes(4), 156: bytes(4), 1: bytes(25), 64: b"\xff\xff"}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    device = device_registry.async_get(original_device.id)
    assert (device.sw_version, device.hw_version, device.serial_number) == (
        "1.2.3.5",
        "0.0.2.3",
        SERIAL,
    )
    for key in ("communications_firmware", "hardware_version", "serial_number", "battery_health"):
        assert hass.states.get(f"sensor.trek_4200_{key}").state == STATE_UNKNOWN
    assert hass.states.get("sensor.trek_4200_battery").state == "89"
    assert hass.states.get("switch.trek_4200_ac_output").state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_charge_limit_number_confirms_readback_and_configuration_category(
    hass, transport, entity_registry
):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = "number.trek_4200_maximum_charge"
    state = hass.states.get(entity_id)
    assert state.state == "90"
    assert state.attributes["unit_of_measurement"] == "%"
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (
        4,
        100,
        1,
    )
    assert entity_registry.async_get(entity_id).entity_category == EntityCategory.CONFIG
    assert not any(frame[35] == 0x32 for frame in transport.peripherals[-1].writes)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 85}, blocking=True
    )
    assert hass.states.get(entity_id).state == "85"
    assert hass.states.get("switch.trek_4200_ac_output").state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("value", [85.5, -1, 101, 3])
async def test_invalid_charge_number_does_not_write(hass, transport, value):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    peripheral = transport.peripherals[-1]
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.trek_4200_maximum_charge", "value": value},
            blocking=True,
        )
    assert not any(frame[35] == 0x32 for frame in peripheral.writes)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_charge_service_failure_does_not_publish_requested_value(hass, transport):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = "number.trek_4200_maximum_charge"
    transport.peripherals[-1].charge_mode = "reject"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": 85}, blocking=True
        )
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    await entry.runtime_data.async_refresh()
    assert hass.states.get(entity_id).state == "90"
    assert await hass.config_entries.async_unload(entry.entry_id)
