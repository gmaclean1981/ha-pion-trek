"""Shared stable identity and device registration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_FINGERPRINT, DOMAIN, MODEL
from .coordinator import TrekCoordinator


class TrekEntity(CoordinatorEntity[TrekCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TrekCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        identity = entry.data[CONF_FINGERPRINT]
        self._attr_unique_id = f"{identity}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identity)},
            connections={(CONNECTION_BLUETOOTH, entry.data[CONF_ADDRESS])},
            name=MODEL,
            manufacturer="Pion Power",
            model=MODEL,
            **coordinator.device_metadata(coordinator.data),
        )
