"""Serialized BLE telemetry and confirmed output changes via HA's transport."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from typing import Any

from bleak import BleakBackend

from .protocol import (
    CHARACTERISTIC_UUID,
    SERVICE_UUID,
    FrameAssembler,
    OutputControlProtocol,
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
        self._protocol = OutputControlProtocol()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self._assembler = FrameAssembler()
        self._lock = asyncio.Lock()
        self._closed = False
        self.device_fingerprint: str | None = None
        self.poll_count = 0
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
        self._protocol = OutputControlProtocol()
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

    async def async_poll(self) -> Telemetry:
        async with self._lock:
            if self._closed:
                raise TrekError("Client is closed")
            try:
                async with asyncio.timeout(70):
                    if not self.connected:
                        await self._open()
                    return await self._read_connected()
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
                                    return value
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
