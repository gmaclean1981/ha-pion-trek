"""Real HA number services and availability for the two additional controls."""

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory

from .test_homeassistant import entry_for
from .test_homeassistant import transport as _transport

transport = _transport


@pytest.mark.parametrize(
    ("suffix", "initial", "changed", "unit", "minimum", "maximum", "step"),
    [
        ("minimum_discharge", 3, 10, "%", 3, 89, 1),
        ("ac_charging_power_limit", 3000, 1200, "W", 100, 3000, 100),
    ],
)
async def test_new_numbers_are_config_entities_with_confirmed_readback(
    hass, transport, entity_registry, suffix, initial, changed, unit, minimum, maximum, step
):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = f"number.trek_4200_{suffix}"
    state = hass.states.get(entity_id)
    assert state.state == str(initial)
    assert state.attributes["unit_of_measurement"] == unit
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (
        minimum,
        maximum,
        step,
    )
    assert entity_registry.async_get(entity_id).entity_category == EntityCategory.CONFIG
    if unit == "W":
        assert state.attributes["device_class"] == "power"
    ble = transport.peripherals[-1]
    assert not any(f[35] == 0x32 for f in ble.writes)
    for requested in (changed, initial):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": requested}, blocking=True
        )
        assert hass.states.get(entity_id).state == str(requested)
        assert hass.states.get("number.trek_4200_maximum_charge").state == "90"
        assert hass.states.get("switch.trek_4200_ac_output").state == "on"
    assert len([f for f in ble.writes if f[35] == 0x32]) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("suffix", "value"),
    [("minimum_discharge", value) for value in [2, 90, 10.5]]
    + [("ac_charging_power_limit", value) for value in [0, 150, 3100, 1200.5]],
)
async def test_invalid_number_values_never_write(hass, transport, suffix, value):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": f"number.trek_4200_{suffix}", "value": value},
            blocking=True,
        )
    assert not any(f[35] == 0x32 for f in transport.peripherals[-1].writes)
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("suffix", "value", "baseline"),
    [("minimum_discharge", 10, "3"), ("ac_charging_power_limit", 1200, "3000")],
)
async def test_failed_write_does_not_show_optimistic_value(
    hass, transport, suffix, value, baseline
):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = f"number.trek_4200_{suffix}"
    transport.peripherals[-1].charge_mode = "reject"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
        )
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    await entry.runtime_data.async_refresh()
    assert hass.states.get(entity_id).state == baseline
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_discharge_change_updates_max_charge_lower_bound(hass, transport):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.trek_4200_minimum_discharge", "value": 20},
        blocking=True,
    )
    assert hass.states.get("number.trek_4200_maximum_charge").attributes["min"] == 21
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.trek_4200_maximum_charge", "value": 80},
        blocking=True,
    )
    assert hass.states.get("number.trek_4200_minimum_discharge").attributes["max"] == 79
    assert await hass.config_entries.async_unload(entry.entry_id)
