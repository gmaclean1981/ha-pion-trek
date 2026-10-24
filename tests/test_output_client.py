"""Confirmed output changes, failed/ambiguous writes, and BLE serialization."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from bleak import BleakError

from custom_components.pion_trek.client import OutputNotConfirmed, TrekClient, TrekError
from custom_components.pion_trek.protocol import ProtocolError, validate_output_tx

from .helpers import CLOCK, FINGERPRINT, FakeBleak


def output_writes(ble):
    return [f for f in ble.writes if f[35] == 0x30 and f[52] == 0x85]


@pytest.mark.parametrize("output", ["ac", "dc", "usb"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_set_each_output_and_confirm_actual_state(output, enabled):
    ble = FakeBleak(stale_reply=True)
    ble.output_states[output] = not enabled
    before = dict(ble.output_states)
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    result = await client.async_set_output(output, enabled)
    assert getattr(result, f"{output}_enabled") is enabled
    assert ble.output_states == {**before, output: enabled}
    assert len(output_writes(ble)) == 1
    validate_output_tx(output_writes(ble)[0])
    assert client.poll_count == 1
    await client.async_close()


async def test_acknowledgement_alone_is_not_success(monkeypatch):
    monkeypatch.setattr("custom_components.pion_trek.client.CONTROL_POLL_SECONDS", 0)
    ble = FakeBleak()
    ble.control_delay_reads = 2
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    assert (await client.async_set_output("dc", True)).dc_enabled
    assert client.poll_count == 3
    assert len(output_writes(ble)) == 1
    await client.async_close()


async def test_ack_without_state_change_times_out_and_disconnects(monkeypatch):
    monkeypatch.setattr("custom_components.pion_trek.client.CONTROL_CONFIRM_SECONDS", 0.02)
    ble = FakeBleak()
    ble.control_mode = "no_change"
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    with pytest.raises(OutputNotConfirmed):
        await client.async_set_output("usb", True)
    assert len(output_writes(ble)) == 1
    assert ble.disconnected
    await client.async_close()


@pytest.mark.parametrize("mode", ["reject", "wrong_value"])
async def test_invalid_acknowledgements_fail_without_replay(mode):
    ble = FakeBleak()
    ble.control_mode = mode
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    with pytest.raises(ProtocolError):
        await client.async_set_output("dc", True)
    assert len(output_writes(ble)) == 1
    assert client.poll_count == 0
    assert ble.disconnected
    await client.async_close()


@pytest.mark.parametrize("mode", ["write_error", "drop_ack"])
async def test_ambiguous_command_is_not_replayed_on_reconnect(mode):
    first, second = FakeBleak(), FakeBleak()
    first.control_mode = mode
    connect = AsyncMock(side_effect=[first, second])
    client = TrekClient(connect, lambda: CLOCK, FINGERPRINT)
    if mode == "drop_ack":
        original = client._receive

        async def short_receive(*args):
            async with asyncio.timeout(0.02):
                return await original(*args)

        client._receive = short_receive
    with pytest.raises((BleakError, TimeoutError)):
        await client.async_set_output("dc", True)
    assert first.disconnected
    assert connect.await_count == 1
    second.output_states = dict(first.output_states)
    assert (await client.async_poll()).dc_enabled
    assert len(output_writes(first)) == 1
    assert not output_writes(second)
    await client.async_close()


async def test_poll_does_not_interleave_with_output_change():
    started, release = asyncio.Event(), asyncio.Event()
    ble = FakeBleak()
    original = ble.write_gatt_char

    async def delayed_write(char, data, response):
        if data[35] == 0x30 and data[52] == 0x85:
            started.set()
            await release.wait()
        await original(char, data, response)

    ble.write_gatt_char = delayed_write
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    change = asyncio.create_task(client.async_set_output("usb", True))
    await started.wait()
    poll = asyncio.create_task(client.async_poll())
    await asyncio.sleep(0)
    assert [f[35] for f in ble.writes] == [4, 2]
    release.set()
    assert (await change).usb_enabled
    assert (await poll).usb_enabled
    assert [f[52] for f in ble.writes if f[35] == 0x30] == [0x85, 0x80, 0x80]
    await client.async_close()


async def test_invalid_arguments_and_closed_client_do_not_connect():
    connect = AsyncMock()
    client = TrekClient(connect, lambda: CLOCK, FINGERPRINT)
    with pytest.raises(ProtocolError):
        await client.async_set_output("main", False)
    with pytest.raises(ProtocolError):
        await client.async_set_output("ac", "off")
    await client.async_close()
    with pytest.raises(TrekError, match="closed"):
        await client.async_set_output("usb", True)
    connect.assert_not_awaited()


async def test_cancelling_control_releases_connection_without_replay():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    await client.async_poll()
    client._receive = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await client.async_set_output("dc", True)
    assert ble.disconnected
    assert len(output_writes(ble)) == 1
    await client.async_close()
