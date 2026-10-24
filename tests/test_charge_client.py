"""Charge limits require fresh settings, acknowledgement and non-optimistic readback."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from bleak import BleakError

from custom_components.pion_trek.charge_protocol import validate_charge_tx
from custom_components.pion_trek.client import ChargeNotConfirmed, TrekClient, TrekError
from custom_components.pion_trek.protocol import ProtocolError

from .helpers import CLOCK, FINGERPRINT, FakeBleak


def charge_writes(ble):
    return [frame for frame in ble.writes if frame[35] == 0x32]


async def test_charge_round_trip_preserves_every_other_setting_and_output():
    ble = FakeBleak(stale_reply=True)
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    original = dict(ble.output_states)
    assert (await client.async_poll()).max_charge_limit == 90
    assert (await client.async_set_charge_limit(85)).max_charge_limit == 85
    assert (await client.async_set_charge_limit(90)).max_charge_limit == 90
    assert ble.output_states == original
    assert ble.other_setting == 100
    assert len(charge_writes(ble)) == 2
    for frame in charge_writes(ble):
        validate_charge_tx(frame)
    await client.async_close()


async def test_settings_refresh_on_timer_and_every_new_connection():
    first, second = FakeBleak(), FakeBleak()
    client = TrekClient(AsyncMock(side_effect=[first, second]), lambda: CLOCK, FINGERPRINT)
    assert (await client.async_poll()).max_charge_limit == 90
    first.max_charge_limit = 85
    assert (await client.async_poll()).max_charge_limit == 90
    assert client.settings_poll_count == 1
    client._settings_read_at -= 61
    assert (await client.async_poll()).max_charge_limit == 85
    assert client.settings_poll_count == 2
    first.is_connected = False
    second.max_charge_limit = 80
    assert (await client.async_poll()).max_charge_limit == 80
    assert client.settings_poll_count == 3
    assert not charge_writes(first) and not charge_writes(second)
    await client.async_close()


async def test_same_limit_is_read_but_never_written():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    assert (await client.async_set_charge_limit(90)).max_charge_limit == 90
    assert not charge_writes(ble)
    await client.async_close()


async def test_fresh_minimum_prevents_crossing_discharge_floor():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    await client.async_poll()
    ble.min_charge_limit = 85
    with pytest.raises(TrekError, match="minimum"):
        await client.async_set_charge_limit(85)
    assert not charge_writes(ble)
    assert ble.disconnected


@pytest.mark.parametrize("value", [-1, 101, 85.5, True, "85"])
async def test_invalid_limit_never_connects(value):
    connect = AsyncMock()
    client = TrekClient(connect, lambda: CLOCK)
    with pytest.raises(ProtocolError):
        await client.async_set_charge_limit(value)
    connect.assert_not_called()


async def test_closed_client_never_connects():
    connect = AsyncMock()
    client = TrekClient(connect, lambda: CLOCK)
    await client.async_close()
    with pytest.raises(TrekError, match="closed"):
        await client.async_set_charge_limit(85)
    connect.assert_not_called()


async def test_delayed_readback_is_confirmed_without_resending(monkeypatch):
    monkeypatch.setattr("custom_components.pion_trek.client.CONTROL_POLL_SECONDS", 0)
    ble = FakeBleak()
    ble.charge_delay_reads = 2
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    assert (await client.async_set_charge_limit(85)).max_charge_limit == 85
    assert client.settings_poll_count == 4
    assert len(charge_writes(ble)) == 1
    await client.async_close()


@pytest.mark.parametrize(
    "mode", ["reject", "wrong_value", "other_setting", "output_changed", "no_change"]
)
async def test_failed_confirmation_is_never_reported_as_success(mode, monkeypatch):
    monkeypatch.setattr("custom_components.pion_trek.client.CONTROL_CONFIRM_SECONDS", 0.02)
    ble = FakeBleak()
    ble.charge_mode = mode
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    with pytest.raises((ProtocolError, ChargeNotConfirmed)):
        await client.async_set_charge_limit(85)
    assert len(charge_writes(ble)) == 1
    assert ble.disconnected


@pytest.mark.parametrize("mode", ["write_error", "drop_ack"])
async def test_ambiguous_write_not_replayed_when_polling_reconnects(mode):
    first, second = FakeBleak(), FakeBleak()
    first.charge_mode = mode
    connect = AsyncMock(side_effect=[first, second])
    client = TrekClient(connect, lambda: CLOCK)
    original = client._receive

    async def bounded_receive(*args):
        async with asyncio.timeout(0.02):
            return await original(*args)

    client._receive = bounded_receive
    with pytest.raises((BleakError, TimeoutError)):
        await client.async_set_charge_limit(85)
    second.max_charge_limit = first.max_charge_limit
    assert (await client.async_poll()).max_charge_limit == 85
    assert len(charge_writes(first)) == 1 and not charge_writes(second)
    await client.async_close()


async def test_settings_failure_disconnects_without_any_setting_write():
    ble = FakeBleak()
    ble.fail_settings = True
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    with pytest.raises(BleakError):
        await client.async_set_charge_limit(85)
    assert not charge_writes(ble)
    assert ble.disconnected


async def test_poll_and_output_change_cannot_interleave_with_charge_transaction():
    started, release = asyncio.Event(), asyncio.Event()
    ble = FakeBleak()
    original = ble.write_gatt_char

    async def delayed_write(char, data, response):
        if data[35] == 0x32:
            started.set()
            await release.wait()
        await original(char, data, response)

    ble.write_gatt_char = delayed_write
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    change = asyncio.create_task(client.async_set_charge_limit(85))
    await started.wait()
    poll = asyncio.create_task(client.async_poll())
    output = asyncio.create_task(client.async_set_output("usb", True))
    await asyncio.sleep(0)
    assert [f[52] for f in ble.writes if f[35] == 0x30] == [0x82, 0x80]
    release.set()
    assert (await change).max_charge_limit == 85
    assert (await poll).max_charge_limit == 85
    assert (await output).usb_enabled
    assert len(charge_writes(ble)) == 1
    await client.async_close()


async def test_cancelling_charge_transaction_disconnects_without_replay():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    original = client._receive

    async def cancelled_ack(opcode, sequence, inner_sequence=None):
        if charge_writes(ble):
            raise asyncio.CancelledError
        return await original(opcode, sequence, inner_sequence)

    client._receive = cancelled_ack
    with pytest.raises(asyncio.CancelledError):
        await client.async_set_charge_limit(85)
    assert ble.disconnected
    assert len(charge_writes(ble)) == 1
