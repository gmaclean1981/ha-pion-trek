"""Offline command compatibility; these fixtures are not live-capture evidence."""

import json
import struct
from pathlib import Path

import pytest

from custom_components.pion_trek.protocol import (
    OutputControlProtocol,
    ProtocolError,
    validate_output_ack,
    validate_output_tx,
    validate_tx,
)

from .helpers import packet, rechecksum

FIXTURES = json.loads((Path(__file__).parent / "fixtures/output_commands.json").read_text())
ACKS = json.loads((Path(__file__).parent / "fixtures/output_acknowledgements.json").read_text())


@pytest.mark.parametrize("sample", ACKS["cases"], ids=lambda s: f"{s['output']}-{s['enabled']}")
def test_captured_acknowledgements(sample):
    validate_output_ack(
        bytes.fromhex(sample["reply_hex"]),
        bytes.fromhex(ACKS["identifier"]),
        bytes.fromhex(ACKS["outer_sequence"]),
        bytes.fromhex(ACKS["inner_sequence"]),
        sample["output"],
        sample["enabled"],
    )


@pytest.mark.parametrize(
    "offset", [4, 8, 10, 35, 36, 37, 38, 44, 47, 48, 52, 53, 54, 55, 57, 58, 59]
)
def test_acknowledgement_must_match_every_command_field(offset):
    sample = ACKS["cases"][0]
    frame = bytearray.fromhex(sample["reply_hex"])
    frame[offset] ^= 1
    # The response header may have been mutated: rechecksum using its actual layout.
    from custom_components.pion_trek.protocol import crc16

    frame[-4:-2] = struct.pack("<H", sum(frame[40:-4]) & 65535)
    frame[-2:] = struct.pack("<H", crc16(frame[2:-2]))
    with pytest.raises(ProtocolError):
        validate_output_ack(
            bytes(frame),
            bytes.fromhex(ACKS["identifier"]),
            bytes.fromhex(ACKS["outer_sequence"]),
            bytes.fromhex(ACKS["inner_sequence"]),
            sample["output"],
            sample["enabled"],
        )


@pytest.mark.parametrize(
    "sample", FIXTURES["commands"], ids=lambda s: f"{s['output']}-{s['enabled']}"
)
def test_output_encoding_matches_offline_vendor_encoder(sample):
    protocol = OutputControlProtocol()
    frame = protocol.set_output(sample["output"], sample["enabled"])
    assert frame.hex() == sample["frame_hex"]
    validate_output_tx(frame)
    # Adding the encoder must not open a write path in the existing client.
    with pytest.raises(ProtocolError, match="not an allowed"):
        validate_tx(frame)


@pytest.mark.parametrize("output", ["main", "charger", "fan", "AC", "", 42001, None])
def test_unknown_outputs_rejected_without_advancing_session(output):
    protocol = OutputControlProtocol()
    with pytest.raises(ProtocolError, match="Unsupported output"):
        protocol.set_output(output, True)
    assert protocol.sequence == 0


@pytest.mark.parametrize("value", [0, 1, 2, "on", "off", None, [], {}])
def test_only_explicit_boolean_states_accepted(value):
    protocol = OutputControlProtocol()
    with pytest.raises(ProtocolError, match="boolean"):
        protocol.set_output("ac", value)
    assert protocol.sequence == 0


@pytest.mark.parametrize("address", [0, 42000, 42004, 42050, 42199, 42500, 65535])
def test_other_registers_rejected_even_with_valid_checksums(address):
    frame = bytearray(OutputControlProtocol().set_output("dc", False))
    struct.pack_into("<H", frame, 54, address)
    with pytest.raises(ProtocolError, match="Not an allowed"):
        validate_output_tx(rechecksum(frame, inner=True))


@pytest.mark.parametrize(
    ("offset", "value"),
    [
        (8, 5),
        (35, 0x32),
        (36, 2),
        (37, 21),
        (46, 9),
        (51, 3),
        (52, 0x84),
        (53, 2),
        (56, 2),
        (57, 1),
        (58, 2),
        (58, 255),
    ],
)
def test_modified_command_shape_rejected(offset, value):
    frame = bytearray(OutputControlProtocol().set_output("usb", True))
    frame[offset] = value
    with pytest.raises(ProtocolError):
        validate_output_tx(rechecksum(frame, inner=True))


def test_read_frames_cannot_be_used_as_output_commands():
    for name in ("hello", "platform", "request", "response"):
        with pytest.raises(ProtocolError):
            validate_output_tx(packet(name))


def test_invalid_command_checksum_rejected():
    frame = bytearray(OutputControlProtocol().set_output("ac", True))
    frame[-1] ^= 1
    with pytest.raises(ProtocolError, match="CRC"):
        validate_output_tx(bytes(frame))
