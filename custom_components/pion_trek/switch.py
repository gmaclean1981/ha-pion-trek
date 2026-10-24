"""AC/DC/USB output switches, reporting confirmed physical state."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TrekCoordinator
from .entity import TrekEntity

PARALLEL_UPDATES = 0
SWITCHES = tuple(
    SwitchEntityDescription(
        key=output,
        translation_key=output,
        device_class=SwitchDeviceClass.OUTLET,
        icon=icon,
    )
    for output, icon in (
        ("ac", "mdi:power-socket-us"),
        ("dc", "mdi:current-dc"),
        ("usb", "mdi:usb-port"),
    )
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[TrekCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        TrekOutputSwitch(entry.runtime_data, entry, description) for description in SWITCHES
    )


class TrekOutputSwitch(TrekEntity, SwitchEntity):
    def __init__(
        self,
        coordinator: TrekCoordinator,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        # Deliberately distinct from the existing *_enabled binary-sensor IDs.
        super().__init__(coordinator, entry, f"{description.key}_output")
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return getattr(self.coordinator.data, f"{self.entity_description.key}_enabled")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_output(self.entity_description.key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_output(self.entity_description.key, False)
