"""Retain existing output-status entities and their history alongside switches."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TrekCoordinator
from .entity import TrekEntity

PARALLEL_UPDATES = 0
SENSORS = tuple(
    BinarySensorEntityDescription(key=key, translation_key=key, icon="mdi:power-socket-us")
    for key in ("ac_enabled", "dc_enabled", "usb_enabled")
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[TrekCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        TrekBinarySensor(entry.runtime_data, entry, description) for description in SENSORS
    )


class TrekBinarySensor(TrekEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: TrekCoordinator,
        entry: ConfigEntry,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return getattr(self.coordinator.data, self.entity_description.key)
