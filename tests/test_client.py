"""Exercise the actual client with a fake peripheral, including reconnection."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bleak import BleakBackend, BleakError

from custom_components.pion_trek.client import (
    IdentityMismatch,
    TrekClient,
    TrekError,
    UnsupportedDevice,
)
from custom_components.pion_trek.protocol import validate_tx

from .helpers import CLOCK, FINGERPRINT, FakeBleak


async def test_persistent_connection_and_stale_reply():
    ble = FakeBleak(stale_reply=True)
    connect = AsyncMock(return_value=ble)
    client = TrekClient(connect, lambda: CLOCK, FINGERPRINT)
    assert (await client.async_poll()).battery_level == 89
    assert (await client.async_poll()).output_power == 381
    assert client.poll_count == 2
    assert client.device_fingerprint == FINGERPRINT
    assert connect.await_count == 1
    assert [f[35] for f in ble.writes] == [4, 2, 0x30, 0x30]
    for frame in ble.writes:
        validate_tx(frame)
    await client.async_close()
    assert ble.disconnected
    with pytest.raises(TrekError, match="closed"):
        await client.async_poll()


async def test_failed_poll_disconnects_and_next_poll_reconnects():
    first, second = FakeBleak(fail_read=True), FakeBleak()
    connect = AsyncMock(side_effect=[first, second])
    client = TrekClient(connect, lambda: CLOCK, FINGERPRINT)
    with pytest.raises(BleakError):
        await client.async_poll()
    assert first.disconnected
    assert (await client.async_poll()).battery_level == 89
    assert client.connection_count == 2
    await client.async_close()


async def test_identity_changed_blocks_telemetry():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, "wrong")
    with pytest.raises(IdentityMismatch):
        await client.async_poll()
    assert [f[35] for f in ble.writes] == [4]
    assert ble.disconnected


async def test_small_mtu_refuses_unverified_fragmentation():
    ble = FakeBleak(mtu=23)
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    with pytest.raises(UnsupportedDevice, match="MTU"):
        await client.async_poll()
    assert not ble.writes
    assert ble.disconnected


@pytest.mark.parametrize("negotiated_mtu", [23, 517])
async def test_bluez_acquires_real_mtu_before_subscribing(negotiated_mtu):
    ble = FakeBleak(mtu=23)
    ble.backend_id = BleakBackend.BLUEZ_DBUS

    async def acquire():
        assert ble.notify is None
        assert not ble.writes
        ble.mtu_size = negotiated_mtu

    ble._backend = SimpleNamespace(_acquire_mtu=AsyncMock(side_effect=acquire))
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    if negotiated_mtu < 89:
        with pytest.raises(UnsupportedDevice, match="MTU"):
            await client.async_poll()
        assert not ble.writes
        assert ble.disconnected
    else:
        assert (await client.async_poll()).battery_level == 89
    ble._backend._acquire_mtu.assert_awaited_once()
    assert client.mtu == negotiated_mtu
    await client.async_close()


async def test_proxy_does_not_use_bluez_mtu_workaround():
    ble = FakeBleak()
    ble.backend_id = "esphome"
    ble._backend = SimpleNamespace(_acquire_mtu=AsyncMock())
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    assert (await client.async_poll()).battery_level == 89
    ble._backend._acquire_mtu.assert_not_awaited()
    await client.async_close()


async def test_bluez_mtu_failure_releases_connection():
    ble = FakeBleak(mtu=23)
    ble.backend_id = BleakBackend.BLUEZ_DBUS
    ble._backend = SimpleNamespace(_acquire_mtu=AsyncMock(side_effect=BleakError("Failed")))
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    with pytest.raises(BleakError):
        await client.async_poll()
    assert not ble.writes
    assert ble.disconnected


async def test_timeout_releases_connection():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    client._receive = AsyncMock(side_effect=TimeoutError)
    with pytest.raises(TimeoutError):
        await client.async_poll()
    assert ble.disconnected


async def test_cancellation_releases_connection():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    client._receive = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await client.async_poll()
    assert ble.disconnected
