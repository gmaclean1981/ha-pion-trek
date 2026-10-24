"""Home Assistant Bluetooth routing and shared telemetry polling."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from bleak import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import TrekClient, TrekError
from .const import CONF_FINGERPRINT, DOMAIN, NAME, POLL_INTERVAL
from .protocol import ProtocolError, Telemetry

_LOGGER = logging.getLogger(__name__)


def create_client(
    hass: HomeAssistant, address: str, expected_fingerprint: str | None = None
) -> TrekClient:
    """Use HA's connectable device lookup, including active ESPHome proxies."""

    async def connect() -> BleakClientWithServiceCache:
        device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
        if device is None:
            raise TrekError("Trek is not reachable through a connectable Bluetooth adapter")
        # Create a fresh Bleak client each time; HA selects the usable adapter.
        async with asyncio.timeout(45):
            return await establish_connection(
                BleakClientWithServiceCache,
                device,
                NAME,
                max_attempts=2,
                ble_device_callback=lambda: (
                    bluetooth.async_ble_device_from_address(hass, address, connectable=True)
                    or device
                ),
            )

    return TrekClient(connect, dt_util.now, expected_fingerprint)


class TrekCoordinator(DataUpdateCoordinator[Telemetry]):
    """One read per interval shared by all entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLL_INTERVAL),
            always_update=False,
        )
        self.client = create_client(hass, entry.data[CONF_ADDRESS], entry.data[CONF_FINGERPRINT])
        self._operation_lock = asyncio.Lock()

    async def _async_update_data(self) -> Telemetry:
        try:
            async with self._operation_lock:
                return await self.client.async_poll()
        except (BleakError, TrekError, ProtocolError, OSError, TimeoutError) as err:
            # Do not put BLE addresses, raw identifiers or frames in HA logs.
            raise UpdateFailed(
                f"Trek telemetry unavailable ({type(err).__name__}); check range and close FSpower"
            ) from err

    async def async_set_output(self, output: str, enabled: bool) -> None:
        """Publish actual readback, never an optimistic requested state."""
        async with self._operation_lock:
            try:
                value = await self.client.async_set_output(output, enabled)
            except (BleakError, TrekError, ProtocolError, OSError, TimeoutError) as err:
                # A failed BLE transaction may still have reached the device.
                # Mark state unavailable until the next ordinary read reconciles it.
                self.async_set_update_error(UpdateFailed("Output state needs a fresh reading"))
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="output_not_confirmed",
                ) from err
            self.async_set_updated_data(value)

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.async_close()
