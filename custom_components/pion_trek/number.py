"""Device-confirmed charging configuration, with no startup writes."""

from __future__ import annotations

import math

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .charge_protocol import SETTING_SPECS, Setting
from .const import DOMAIN
from .coordinator import TrekCoordinator
from .entity import TrekEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[TrekCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [TrekSettingNumber(entry.runtime_data, entry, setting) for setting in Setting]
    )


class TrekSettingNumber(TrekEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: TrekCoordinator, entry: ConfigEntry, setting: Setting) -> None:
        super().__init__(coordinator, entry, setting.value)
        self.setting = setting
        self._attr_translation_key = setting.value
        self._attr_native_step = SETTING_SPECS[setting][4]
        if setting == Setting.AC_CHARGE_POWER:
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
            self._attr_device_class = NumberDeviceClass.POWER
            self._attr_icon = "mdi:power-plug"
        else:
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_icon = (
                "mdi:battery-charging-high" if setting == Setting.MAX_CHARGE else "mdi:battery-low"
            )

    @property
    def native_value(self) -> int | None:
        return getattr(self.coordinator.data, self.setting.value)

    @property
    def native_min_value(self) -> int:
        if self.setting == Setting.MAX_CHARGE:
            minimum = self.coordinator.data.min_charge_limit
            return min(100, minimum + 1) if minimum is not None else 0
        return SETTING_SPECS[self.setting][2]

    @property
    def native_max_value(self) -> int:
        if self.setting == Setting.MIN_DISCHARGE:
            maximum = self.coordinator.data.max_charge_limit
            return max(3, min(90, maximum - 1)) if maximum is not None else 90
        return SETTING_SPECS[self.setting][3]

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        if not super().available or self.native_value is None:
            return False
        if self.setting == Setting.AC_CHARGE_POWER:
            return True
        return (
            data.max_charge_limit is not None
            and data.min_charge_limit is not None
            and data.min_charge_limit < 100
            and (self.setting != Setting.MIN_DISCHARGE or data.max_charge_limit > 3)
        )

    async def async_set_native_value(self, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not float(value).is_integer()
            or not self.native_min_value <= value <= self.native_max_value
            or value % self.native_step
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=f"invalid_{self.setting.value}"
            )
        await self.coordinator.async_set_setting(self.setting, int(value))
