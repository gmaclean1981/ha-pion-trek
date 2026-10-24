"""Strict charge-limit framing, query layout and independent transmission gates."""

import struct

import pytest

from custom_components.pion_trek.charge_protocol import (
    ChargeControlProtocol,
    charge_body,
    decode_settings,
    validate_charge_ack,
    validate_charge_tx,
    validate_settings_query,
)
from custom_components.pion_trek.protocol import ProtocolError, validate_output_tx, validate_tx

from .helpers import CHARGE_FIXTURES, IDENTIFIER, SETTINGS_FIXTURE, rechecksum


@pytest.mark.parametrize("case", CHARGE_FIXTURES["cases"])
def test_live_single_register_exchanges(case):
    protocol = ChargeControlProtocol()
    protocol.identifier = IDENTIFIER
    frame = protocol.set_charge_limit(case["value"])
    assert frame.hex() == case["request_hex"]
    validate_charge_tx(frame)
    validate_charge_ack(
        bytes.fromhex(case["reply_hex"]), IDENTIFIER, frame[4:8], frame[47:51], case["value"]
    )


def test_settings_query_matches_captured_layout():
    protocol = ChargeControlProtocol()
    protocol.identifier = IDENTIFIER
    frame = protocol.settings()
    assert frame.hex() == SETTINGS_FIXTURE["request"]
    validate_settings_query(frame)
    reply = bytes.fromhex(SETTINGS_FIXTURE["reply"])
    settings = decode_settings(reply, IDENTIFIER, frame[4:8], frame[47:51])
    assert (settings.max_charge_limit, settings.min_charge_limit) == (90, 3)
    assert "blocks" not in repr(settings)


@pytest.mark.parametrize("value", [0, 4, 85, 90, 100])
def test_only_one_charge_register_is_encoded(value):
    frame = ChargeControlProtocol().set_charge_limit(value)
    assert len(frame) == 63
    assert frame[35] == 0x32 and frame[52] == 0x84
    assert frame[53:-4] == b"\x01\x4b\xa4\x01\x00" + bytes([value])
    validate_charge_tx(frame)
    for other_gate in (validate_tx, validate_output_tx, validate_settings_query):
        with pytest.raises(ProtocolError):
            other_gate(frame)


@pytest.mark.parametrize("value", [-1, 101, True, 85.5, 85.0, "90", None])
def test_invalid_limit_rejected_before_sequence_changes(value):
    protocol = ChargeControlProtocol()
    with pytest.raises(ProtocolError):
        protocol.set_charge_limit(value)
    assert protocol.sequence == 0


@pytest.mark.parametrize("offset", [8, 9, 35, 36, 37, 43, 44, 45, 46, 51, 52, 53, 54, 55, 56, 57])
def test_charge_gate_rejects_changed_headers_register_and_block_shape(offset):
    frame = bytearray(ChargeControlProtocol().set_charge_limit(85))
    frame[offset] ^= 1
    with pytest.raises(ProtocolError):
        validate_charge_tx(rechecksum(frame, inner=True))


def test_charge_gate_refuses_multi_register_writes():
    protocol = ChargeControlProtocol()
    frame = protocol._charge_frame(
        0x32, 0x84, b"\x02" + charge_body(85)[1:] + struct.pack("<HHB", 42001, 1, 0)
    )
    with pytest.raises(ProtocolError):
        validate_charge_tx(frame)


@pytest.mark.parametrize("offset", [8, 9, 35, 36, 37, 43, 45, 51, 52, 53, 54, 56, 57, 58])
def test_settings_query_gate_refuses_altered_query(offset):
    frame = bytearray.fromhex(SETTINGS_FIXTURE["request"])
    frame[offset] ^= 1
    with pytest.raises(ProtocolError):
        validate_settings_query(rechecksum(frame, inner=True))


@pytest.mark.parametrize(
    "offset", [4, 8, 10, 35, 36, 37, 38, 44, 45, 47, 48, 52, 53, 54, 55, 57, 58]
)
def test_settings_reply_rejects_wrong_identity_sequences_and_layout(offset):
    frame = bytearray.fromhex(SETTINGS_FIXTURE["reply"])
    frame[offset] ^= 1
    # Keep checksum valid even when mutating the outer opcode.
    from custom_components.pion_trek.protocol import crc16

    frame[-4:-2] = struct.pack("<H", sum(frame[40:-4]) & 65535)
    frame[-2:] = struct.pack("<H", crc16(frame[2:-2]))
    with pytest.raises(ProtocolError):
        decode_settings(
            bytes(frame), IDENTIFIER, bytes.fromhex("00000002"), bytes.fromhex("00000001")
        )


@pytest.mark.parametrize("offset", [118, 119])
def test_invalid_percentages_in_settings_refused(offset):
    frame = bytearray.fromhex(SETTINGS_FIXTURE["reply"])
    frame[offset] = 101
    with pytest.raises(ProtocolError):
        decode_settings(rechecksum(frame, inner=True), IDENTIFIER, frame[4:8], frame[48:52])


def charge_ack():
    return bytes.fromhex(CHARGE_FIXTURES["cases"][0]["reply_hex"])


def test_charge_acknowledgement_must_echo_the_requested_setting():
    frame = charge_ack()
    validate_charge_ack(frame, IDENTIFIER, frame[4:8], frame[48:52], 85)
    with pytest.raises(ProtocolError):
        validate_charge_ack(frame, IDENTIFIER, frame[4:8], frame[48:52], 90)


@pytest.mark.parametrize(
    "offset", [4, 8, 10, 35, 36, 37, 38, 44, 47, 48, 52, 53, 54, 55, 57, 58, 59]
)
def test_charge_ack_rejects_mismatch_even_with_valid_checksums(offset):
    from custom_components.pion_trek.protocol import crc16

    original = charge_ack()
    frame = bytearray(original)
    frame[offset] ^= 1
    frame[-4:-2] = struct.pack("<H", sum(frame[40:-4]) & 65535)
    frame[-2:] = struct.pack("<H", crc16(frame[2:-2]))
    with pytest.raises(ProtocolError):
        validate_charge_ack(bytes(frame), IDENTIFIER, original[4:8], original[48:52], 85)
