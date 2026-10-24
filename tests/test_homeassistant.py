"""Real HA config flows/platforms with synthetic BLE transport."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS, STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pion_trek.client import TrekClient
from custom_components.pion_trek.const import CONF_FINGERPRINT, DOMAIN
from custom_components.pion_trek.diagnostics import async_get_config_entry_diagnostics

from .helpers import ADDRESS, CLOCK, FINGERPRINT, FakeBleak


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
    assert len(trek) == 10
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
    assert diagnostic["integration_version"] == "0.2.0"
    assert diagnostic["successful_polls"] == 2
    assert diagnostic["connections"] == 2
    assert ADDRESS not in json.dumps(diagnostic)
    assert FINGERPRINT not in json.dumps(diagnostic)

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
