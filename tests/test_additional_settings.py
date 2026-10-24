"""Charge controls must preserve adjacent settings and reconcile actual readback."""

import asyncio
import json
import struct
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bleak import BleakError

from custom_components.pion_trek.charge_protocol import (
    ChargeControlProtocol,
    Setting,
    decode_settings,
    validate_charge_tx,
    validate_setting_ack,
    validate_setting_tx,
)
from custom_components.pion_trek.client import ChargeNotConfirmed, TrekClient, TrekError
from custom_components.pion_trek.protocol import ProtocolError, validate_output_tx, validate_tx

from .helpers import CLOCK, FINGERPRINT, IDENTIFIER, SETTINGS_FIXTURE, FakeBleak, rechecksum

NEW_SETTINGS = [Setting.MIN_DISCHARGE, Setting.AC_CHARGE_POWER]
TRIAL_VALUE = {Setting.MIN_DISCHARGE: 10, Setting.AC_CHARGE_POWER: 1200}
BASELINE = {Setting.MIN_DISCHARGE: 3, Setting.AC_CHARGE_POWER: 3000}
LIVE_EXCHANGES = json.loads(
    (Path(__file__).parent / "fixtures/additional_settings_acknowledgements.json").read_text()
)


@pytest.mark.parametrize("case", LIVE_EXCHANGES["cases"])
def test_confirmed_hardware_single_register_exchanges(case):
    protocol = ChargeControlProtocol()
    protocol.identifier = IDENTIFIER
    setting = Setting(case["setting"])
    request = protocol.set_setting(setting, case["value"])
    assert request.hex() == case["request_hex"]
    validate_setting_tx(request, setting)
    validate_setting_ack(
        bytes.fromhex(case["reply_hex"]),
        IDENTIFIER,
        request[4:8],
        request[47:51],
        setting,
        case["value"],
    )


def setting_writes(ble):
    return [frame for frame in ble.writes if frame[35] == 0x32]


@pytest.mark.parametrize(
    ("setting", "value", "body"),
    [
        (Setting.MIN_DISCHARGE, 3, "014ca4010003"),
        (Setting.MIN_DISCHARGE, 90, "014ca401005a"),
        (Setting.AC_CHARGE_POWER, 100, "0164b202006400"),
        (Setting.AC_CHARGE_POWER, 3000, "0164b20200b80b"),
    ],
)
def test_register_width_endianness_and_intent_gate(setting, value, body):
    frame = ChargeControlProtocol().set_setting(setting, value)
    assert frame[53:-4].hex() == body
    validate_setting_tx(frame, setting)
    for other in Setting:
        if other != setting:
            with pytest.raises(ProtocolError):
                validate_setting_tx(frame, other)
    for gate in (validate_tx, validate_output_tx, validate_charge_tx):
        with pytest.raises(ProtocolError):
            gate(frame)


@pytest.mark.parametrize("setting", NEW_SETTINGS)
@pytest.mark.parametrize("offset", [8, 9, 35, 36, 37, 43, 44, 45, 46, 51, 52, 53, 54, 55, 56, 57])
def test_valid_checksum_cannot_bypass_target_or_shape(setting, offset):
    frame = bytearray(ChargeControlProtocol().set_setting(setting, TRIAL_VALUE[setting]))
    frame[offset] ^= 1
    with pytest.raises(ProtocolError):
        validate_setting_tx(rechecksum(frame, inner=True), setting)


@pytest.mark.parametrize(
    ("setting", "value"),
    [(Setting.MIN_DISCHARGE, v) for v in [2, 91, True, 10.0, "10", None]]
    + [(Setting.AC_CHARGE_POWER, v) for v in [0, 99, 3100, 150, 100.0, True, "1200", None]],
)
async def test_invalid_input_rejected_without_connection_or_sequence_change(setting, value):
    proto = ChargeControlProtocol()
    with pytest.raises(ProtocolError):
        proto.set_setting(setting, value)
    assert proto.sequence == 0
    connect = AsyncMock()
    with pytest.raises(ProtocolError):
        await TrekClient(connect, lambda: CLOCK).async_set_setting(setting, value)
    connect.assert_not_called()


def test_unknown_setting_refused():
    with pytest.raises(ProtocolError):
        ChargeControlProtocol().set_setting("arbitrary", 1)


@pytest.mark.parametrize("watts", [0, 1200, 3000, 3001, 65535])
def test_ac_limit_readback_scales_and_unknown_values(watts):
    frame = bytearray.fromhex(SETTINGS_FIXTURE["reply"])
    struct.pack_into("<H", frame, 163, watts)
    settings = decode_settings(rechecksum(frame, inner=True), IDENTIFIER, frame[4:8], frame[48:52])
    assert settings.ac_charge_power_limit == (watts if watts <= 3000 else None)
    assert settings.min_charge_limit == 3


def test_each_settings_comparison_masks_only_its_own_bytes():
    baseline = bytearray.fromhex(SETTINGS_FIXTURE["reply"])

    def decode(frame):
        return decode_settings(rechecksum(frame, inner=True), IDENTIFIER, frame[4:8], frame[48:52])

    before = decode(baseline)
    for target, offset, payload in [
        (Setting.MAX_CHARGE, 118, b"\x55"),
        (Setting.MIN_DISCHARGE, 119, b"\x0a"),
        (Setting.AC_CHARGE_POWER, 163, struct.pack("<H", 1200)),
    ]:
        frame = bytearray(baseline)
        frame[offset : offset + len(payload)] = payload
        after = decode(frame)
        for selected in Setting:
            assert (before.other_settings(selected) == after.other_settings(selected)) == (
                selected == target
            )


@pytest.mark.parametrize("setting", NEW_SETTINGS)
async def test_new_control_round_trip_and_noop_preserve_other_settings(setting):
    ble = FakeBleak(stale_reply=True)
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK, FINGERPRINT)
    before = await client.async_poll()
    assert getattr(before, setting.value) == BASELINE[setting]
    assert not setting_writes(ble)
    for requested in (TRIAL_VALUE[setting], BASELINE[setting], BASELINE[setting]):
        value = await client.async_set_setting(setting, requested)
        assert getattr(value, setting.value) == requested
        for other in Setting:
            if other != setting:
                assert getattr(value, other.value) == getattr(before, other.value)
        assert (value.ac_enabled, value.dc_enabled, value.usb_enabled) == (True, False, False)
    assert len(setting_writes(ble)) == 2
    await client.async_close()


async def test_fresh_upper_limit_blocks_invalid_discharge_floor():
    ble = FakeBleak()
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    await client.async_poll()
    ble.max_charge_limit = 20
    with pytest.raises(TrekError, match="below"):
        await client.async_set_discharge_limit(20)
    assert not setting_writes(ble)


@pytest.mark.parametrize("setting", NEW_SETTINGS)
@pytest.mark.parametrize(
    "mode",
    ["reject", "wrong_value", "wrong_register", "other_setting", "output_changed", "no_change"],
)
async def test_new_control_failure_is_unconfirmed_and_never_replayed(setting, mode, monkeypatch):
    monkeypatch.setattr("custom_components.pion_trek.client.CONTROL_CONFIRM_SECONDS", 0.02)
    ble = FakeBleak()
    ble.charge_mode = mode
    client = TrekClient(AsyncMock(return_value=ble), lambda: CLOCK)
    with pytest.raises((ProtocolError, ChargeNotConfirmed)):
        await client.async_set_setting(setting, TRIAL_VALUE[setting])
    assert len(setting_writes(ble)) == 1
    assert ble.disconnected


@pytest.mark.parametrize("setting", NEW_SETTINGS)
@pytest.mark.parametrize("mode", ["write_error", "drop_ack"])
async def test_ambiguous_new_setting_reconciled_by_read_only(setting, mode):
    first, second = FakeBleak(), FakeBleak()
    first.charge_mode = mode
    client = TrekClient(AsyncMock(side_effect=[first, second]), lambda: CLOCK)
    receive = client._receive

    async def bounded_receive(*args):
        async with asyncio.timeout(0.02):
            return await receive(*args)

    client._receive = bounded_receive
    with pytest.raises((BleakError, TimeoutError)):
        await client.async_set_setting(setting, TRIAL_VALUE[setting])
    setattr(second, setting.value, getattr(first, setting.value))
    assert getattr(await client.async_poll(), setting.value) == TRIAL_VALUE[setting]
    assert len(setting_writes(first)) == 1 and not setting_writes(second)
    await client.async_close()


@pytest.mark.parametrize("setting", NEW_SETTINGS)
async def test_acknowledgement_bound_to_setting_and_value(setting):
    ble = FakeBleak()
    received = []
    ble._emit = received.append
    proto = ChargeControlProtocol()
    proto.identifier = IDENTIFIER
    request = proto.set_setting(setting, TRIAL_VALUE[setting])
    await ble.write_gatt_char(ble.char, request, True)
    reply = received[-1]
    validate_setting_ack(
        reply, IDENTIFIER, request[4:8], request[47:51], setting, TRIAL_VALUE[setting]
    )
    for other in Setting:
        if other != setting:
            with pytest.raises(ProtocolError):
                validate_setting_ack(reply, IDENTIFIER, request[4:8], request[47:51], other, 100)
