"""Device-confirmed maximum battery charge, with no startup writes."""

from __future__ import annotations

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TrekCoordinator
from .entity import TrekEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[TrekCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TrekChargeLimit(entry.runtime_data, entry)])


class TrekChargeLimit(TrekEntity, NumberEntity):
    _attr_translation_key = "max_charge_limit"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:battery-charging-high"

    def __init__(self, coordinator: TrekCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "max_charge_limit")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.max_charge_limit

    @property
    def native_min_value(self) -> int:
        minimum = self.coordinator.data.min_charge_limit
        return min(100, minimum + 1) if minimum is not None else 0

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data.max_charge_limit is not None
            and data.min_charge_limit is not None
            and data.min_charge_limit < 100
        )

    async def async_set_native_value(self, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not float(value).is_integer()
            or not self.native_min_value <= value <= 100
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_charge_limit"
            )
        await self.coordinator.async_set_charge_limit(int(value))
