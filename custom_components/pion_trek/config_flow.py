"""Discover a candidate, then verify a real telemetry response before setup."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from bleak import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers import selector

from .client import InsufficientMTU, TrekError, UnsupportedDevice
from .const import CONF_FINGERPRINT, DOMAIN, MODEL, NAME
from .coordinator import create_client
from .protocol import SERVICE_UUID, ProtocolError


class TrekConfigFlow(ConfigFlow, domain=DOMAIN):
    """No account, password, MQTT broker or companion service is required."""

    VERSION = 1
    _address: str

    async def _verify(self) -> ConfigFlowResult | str:
        client = create_client(self.hass, self._address)
        try:
            await client.async_poll()
            device_fingerprint = client.device_fingerprint
        except InsufficientMTU:
            return "insufficient_mtu"
        except UnsupportedDevice, ProtocolError:
            return "unsupported_device"
        except BleakError, TrekError, OSError, TimeoutError:
            return "cannot_connect"
        finally:
            await client.async_close()
        if not device_fingerprint:
            return "unsupported_device"
        return self.async_create_entry(
            title=MODEL,
            data={CONF_ADDRESS: self._address, CONF_FINGERPRINT: device_fingerprint},
        )

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        # HA requires at least three literal characters in manifest name
        # patterns. Filter the app's two-character prefix here instead.
        if not discovery_info.name.startswith("TM"):
            return self.async_abort(reason="not_supported")
        self._address = discovery_info.address.upper()
        await self.async_set_unique_id(self._address)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": NAME}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            result = await self._verify()
            if not isinstance(result, str):
                return result
            errors["base"] = result
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"address": self._address},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            address = str(user_input[CONF_ADDRESS]).strip().upper()
            if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                self._address = address
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                result = await self._verify()
                if not isinstance(result, str):
                    return result
                errors["base"] = result
        current = self._async_current_ids()
        options = [
            selector.SelectOptionDict(
                value=info.address.upper(), label=f"{info.name} ({info.address})"
            )
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if SERVICE_UUID in info.service_uuids
            and info.name.startswith("TM")
            and info.address.upper() not in current
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )
