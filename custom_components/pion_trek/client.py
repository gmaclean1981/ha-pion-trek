"""Serialized BLE telemetry and confirmed output changes via HA's transport."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from typing import Any

from bleak import BleakBackend

from .charge_protocol import (
    ChargeControlProtocol,
    ChargeSettings,
    Setting,
    decode_settings,
    setting_body,
    validate_charge_tx,
    validate_setting_ack,
    validate_setting_tx,
    validate_settings_query,
)
from .protocol import (
    CHARACTERISTIC_UUID,
    SERVICE_UUID,
    FrameAssembler,
    Telemetry,
    decode_telemetry,
    fingerprint,
    output_command_body,
    validate_output_ack,
    validate_output_tx,
    validate_tx,
)

SESSION_SETTLE_SECONDS = 1
CONTROL_CONFIRM_SECONDS = 20
CONTROL_POLL_SECONDS = 2
SETTINGS_POLL_SECONDS = 60


class TrekError(Exception):
    """A connection or device compatibility problem."""


class UnsupportedDevice(TrekError):
    """The device does not match the tested protocol."""


class InsufficientMTU(UnsupportedDevice):
    """The negotiated MTU cannot carry the tested telemetry request."""


class IdentityMismatch(TrekError):
    """The device identity changed since setup."""


class OutputNotConfirmed(TrekError):
    """A write was acknowledged, but its requested state was not confirmed."""


class ChargeNotConfirmed(TrekError):
    """The charge limit or unchanged surrounding settings could not be verified."""


class TrekClient:
    """One persistent connection, serialized polling, clean reconnects."""

    def __init__(
        self,
        connect: Callable[[], Awaitable[Any]],
        now: Callable[[], datetime],
        expected_fingerprint: str | None = None,
    ) -> None:
        self._connect = connect
        self._now = now
        self._expected_fingerprint = expected_fingerprint
        self._client: Any = None
        self._characteristic: Any = None
        self._protocol = ChargeControlProtocol()
        self._settings: ChargeSettings | None = None
        self._settings_read_at = 0.0
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self._assembler = FrameAssembler()
        self._lock = asyncio.Lock()
        self._closed = False
        self.device_fingerprint: str | None = None
        self.poll_count = 0
        self.settings_poll_count = 0
        self.connection_count = 0
        self.mtu: int | None = None
        self.backend: str | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def invalid_frames(self) -> int:
        return self._assembler.invalid_frames

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        self._characteristic = None
        self._settings = None
        if client is not None:
            with suppress(Exception):
                async with asyncio.timeout(10):
                    await client.disconnect()

    async def async_close(self) -> None:
        self._closed = True
        async with self._lock:
            await self._disconnect()

    async def _send(self, frame: bytes) -> None:
        validate_tx(frame)
        async with asyncio.timeout(12):
            await self._client.write_gatt_char(self._characteristic, frame, response=True)

    async def _send_output(self, frame: bytes) -> None:
        # This separate path cannot transmit bulk settings or arbitrary registers.
        validate_output_tx(frame)
        async with asyncio.timeout(12):
            await self._client.write_gatt_char(self._characteristic, frame, response=True)

    async def _send_settings_query(self, frame: bytes) -> None:
        validate_settings_query(frame)
        async with asyncio.timeout(12):
            await self._client.write_gatt_char(self._characteristic, frame, response=True)

    async def _send_charge_limit(self, frame: bytes) -> None:
        validate_charge_tx(frame)
        async with asyncio.timeout(12):
            await self._client.write_gatt_char(self._characteristic, frame, response=True)

    async def _send_setting(self, frame: bytes, setting: Setting) -> None:
        validate_setting_tx(frame, setting)
        async with asyncio.timeout(12):
            await self._client.write_gatt_char(self._characteristic, frame, response=True)

    async def _receive(
        self, opcode: int, sequence: bytes, inner_sequence: bytes | None = None
    ) -> bytes:
        async with asyncio.timeout(12):
            while True:
                frame = await self._queue.get()
                if frame[35] == opcode and frame[4:8] == sequence:
                    if inner_sequence is not None and frame[48:52] != inner_sequence:
                        continue  # A delayed reply can share a newer outer sequence.
                    return frame

    async def _open(self) -> None:
        await self._disconnect()
        # Old notification callbacks retain their old queue/assembler.
        queue = self._queue = asyncio.Queue(maxsize=32)
        assembler = self._assembler = FrameAssembler()
        self._protocol = ChargeControlProtocol()
        self._client = await self._connect()
        self.connection_count += 1
        service = self._client.services.get_service(SERVICE_UUID)
        char = service.get_characteristic(CHARACTERISTIC_UUID) if service else None
        if char is None or not {"write", "notify"}.issubset(char.properties):
            raise UnsupportedDevice("Expected Trek write/notify service was not found")
        backend_id = getattr(self._client, "backend_id", None)
        self.backend = str(backend_id) if backend_id is not None else None
        if backend_id == BleakBackend.BLUEZ_DBUS:
            # Bleak's BlueZ mtu_size otherwise returns the default 23. Follow
            # its mtu_size example before subscribing; AcquireNotify must not
            # compete with our notification subscription. HA exposes the
            # selected underlying backend, including on its client wrapper.
            async with asyncio.timeout(12):
                await self._client._backend._acquire_mtu()
        self.mtu = self._client.mtu_size
        if self.mtu < 89:
            raise InsufficientMTU(
                "Bluetooth MTU is below 89; this connection cannot carry the tested request"
            )
        self._characteristic = char

        def notify(_: Any, data: bytearray) -> None:
            for frame in assembler.feed(bytes(data)):
                if not queue.full():
                    queue.put_nowait(frame)

        await self._client.start_notify(char, notify)
        await asyncio.sleep(SESSION_SETTLE_SECONDS)
        hello = self._protocol.hello(self._now())
        await self._send(hello)
        reply = await self._receive(1, hello[4:8])
        identifier = reply[10:35]
        if identifier == bytes(25):
            raise UnsupportedDevice("Device did not supply an identity")
        value = fingerprint(identifier)
        if self._expected_fingerprint and value != self._expected_fingerprint:
            raise IdentityMismatch("Device identity differs from the one verified during setup")
        self.device_fingerprint = value
        self._protocol.identifier = identifier
        await self._send(self._protocol.platform(self._now()))
        await asyncio.sleep(SESSION_SETTLE_SECONDS)

    async def _read_connected(self) -> Telemetry:
        request = self._protocol.telemetry()
        await self._send(request)
        frame = await self._receive(0x31, request[4:8], request[47:51])
        value = decode_telemetry(frame, self._protocol.identifier, request[47:51])
        self.poll_count += 1
        return value

    async def _read_settings_connected(self) -> ChargeSettings:
        request = self._protocol.settings()
        await self._send_settings_query(request)
        reply = await self._receive(0x33, request[4:8], request[47:51])
        settings = decode_settings(reply, self._protocol.identifier, request[4:8], request[47:51])
        self._settings = settings
        self._settings_read_at = asyncio.get_running_loop().time()
        self.settings_poll_count += 1
        return settings

    async def _with_settings(self, value: Telemetry) -> Telemetry:
        if (
            self._settings is None
            or asyncio.get_running_loop().time() - self._settings_read_at >= SETTINGS_POLL_SECONDS
        ):
            await self._read_settings_connected()
        return replace(
            value,
            max_charge_limit=self._settings.max_charge_limit,
            min_charge_limit=self._settings.min_charge_limit,
            ac_charge_power_limit=self._settings.ac_charge_power_limit,
        )

    async def async_poll(self) -> Telemetry:
        async with self._lock:
            if self._closed:
                raise TrekError("Client is closed")
            try:
                async with asyncio.timeout(70):
                    if not self.connected:
                        await self._open()
                    return await self._with_settings(await self._read_connected())
            except asyncio.CancelledError:
                await self._disconnect()
                raise
            except Exception:
                await self._disconnect()
                raise

    async def async_set_output(self, output: str, enabled: bool) -> Telemetry:
        """Send once, validate acknowledgement, then confirm actual output state.

        A failed or cancelled operation is never replayed on reconnect. Its
        physical outcome may be unknown; later polls reconcile the real state.
        """
        output_command_body(output, enabled)
        async with self._lock:
            if self._closed:
                raise TrekError("Client is closed")
            try:
                async with asyncio.timeout(90):
                    if not self.connected:
                        await self._open()
                    request = self._protocol.set_output(output, enabled)
                    await self._send_output(request)
                    reply = await self._receive(0x33, request[4:8], request[47:51])
                    validate_output_ack(
                        reply,
                        self._protocol.identifier,
                        request[4:8],
                        request[47:51],
                        output,
                        enabled,
                    )
                    try:
                        async with asyncio.timeout(CONTROL_CONFIRM_SECONDS):
                            while True:
                                value = await self._read_connected()
                                if getattr(value, f"{output}_enabled") == enabled:
                                    return await self._with_settings(value)
                                await asyncio.sleep(CONTROL_POLL_SECONDS)
                    except TimeoutError as err:
                        raise OutputNotConfirmed(
                            "Requested output state was not confirmed"
                        ) from err
            except asyncio.CancelledError:
                await self._disconnect()
                raise
            except Exception:
                await self._disconnect()
                raise

    async def async_set_charge_limit(self, limit: int) -> Telemetry:
        return await self.async_set_setting(Setting.MAX_CHARGE, limit)

    async def async_set_discharge_limit(self, limit: int) -> Telemetry:
        return await self.async_set_setting(Setting.MIN_DISCHARGE, limit)

    async def async_set_ac_charge_power(self, watts: int) -> Telemetry:
        return await self.async_set_setting(Setting.AC_CHARGE_POWER, watts)

    async def async_set_setting(self, setting: Setting, limit: int) -> Telemetry:
        """Write exactly one register once, then confirm it with fresh settings.

        A fresh pre-read protects the minimum discharge limit and lets us detect
        changes to other settings. Never replay a failed or ambiguous write.
        """
        setting_body(setting, limit)
        async with self._lock:
            if self._closed:
                raise TrekError("Client is closed")
            try:
                async with asyncio.timeout(90):
                    if not self.connected:
                        await self._open()
                    before = await self._read_settings_connected()
                    if setting == Setting.MAX_CHARGE and limit <= before.min_charge_limit:
                        raise TrekError("Maximum charge must exceed the minimum discharge limit")
                    if setting == Setting.MIN_DISCHARGE and limit >= before.max_charge_limit:
                        raise TrekError(
                            "Minimum discharge must stay below the maximum charge limit"
                        )
                    if getattr(before, setting.value) is None:
                        raise TrekError("The device did not report a supported charging setting")
                    telemetry_before = await self._read_connected()
                    if limit == getattr(before, setting.value):
                        return await self._with_settings(telemetry_before)
                    request = self._protocol.set_setting(setting, limit)
                    if setting == Setting.MAX_CHARGE:
                        await self._send_charge_limit(request)
                    else:
                        await self._send_setting(request, setting)
                    reply = await self._receive(0x33, request[4:8], request[47:51])
                    validate_setting_ack(
                        reply,
                        self._protocol.identifier,
                        request[4:8],
                        request[47:51],
                        setting,
                        limit,
                    )
                    try:
                        async with asyncio.timeout(CONTROL_CONFIRM_SECONDS):
                            while True:
                                after = await self._read_settings_connected()
                                if after.other_settings(setting) != before.other_settings(setting):
                                    raise ChargeNotConfirmed(
                                        "Other device settings changed during the command"
                                    )
                                if getattr(after, setting.value) == limit:
                                    telemetry_after = await self._read_connected()
                                    if any(
                                        getattr(telemetry_before, key)
                                        != getattr(telemetry_after, key)
                                        for key in ("ac_enabled", "dc_enabled", "usb_enabled")
                                    ):
                                        raise ChargeNotConfirmed(
                                            "Output states changed during the command"
                                        )
                                    return await self._with_settings(telemetry_after)
                                await asyncio.sleep(CONTROL_POLL_SECONDS)
                    except TimeoutError as err:
                        raise ChargeNotConfirmed("Charging setting was not confirmed") from err
            except asyncio.CancelledError:
                await self._disconnect()
                raise
            except Exception:
                await self._disconnect()
                raise
