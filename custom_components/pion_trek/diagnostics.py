"""Minimal diagnostics without device identifiers or packet contents."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, POLL_INTERVAL
from .coordinator import TrekCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[TrekCoordinator]
) -> dict:
    coordinator = entry.runtime_data
    client = coordinator.client
    integration = await async_get_integration(hass, DOMAIN)
    return {
        "integration_version": integration.version,
        "poll_interval_seconds": POLL_INTERVAL,
        "last_update_success": coordinator.last_update_success,
        "bluetooth_connected": client.connected,
        "negotiated_mtu": client.mtu,
        "bluetooth_backend": client.backend,
        "successful_polls": client.poll_count,
        "successful_settings_reads": client.settings_poll_count,
        "connections": client.connection_count,
        "invalid_frames_current_session": client.invalid_frames,
    }
