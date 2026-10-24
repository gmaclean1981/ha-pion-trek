"""Wire compatibility, strict read-only boundary and response validation."""

import struct

import pytest

from custom_components.pion_trek.protocol import (
    FrameAssembler,
    ProtocolError,
    ReadOnlyProtocol,
    crc16,
    decode_telemetry,
    validate_inner,
    validate_outer,
    validate_tx,
)

from .helpers import CLOCK, IDENTIFIER, packet, rechecksum


def test_known_frames():
    p = ReadOnlyProtocol()
    assert p.hello(CLOCK) == packet("hello")
    p.identifier = IDENTIFIER
    assert p.platform(CLOCK) == packet("platform")
    assert p.telemetry() == packet("request")
    for name in ("hello", "platform", "request"):
        validate_tx(packet(name))
    assert crc16(b"123456789") == 0x4B37


def test_decimal_sequence_rollover():
    p = ReadOnlyProtocol()
    p.sequence = 8
    assert p._next_sequence() == bytes.fromhex("00000009")
    assert p._next_sequence() == bytes.fromhex("00000010")
    p.sequence = 99999999
    assert p._next_sequence() == bytes.fromhex("00000001")


@pytest.mark.parametrize("opcode", [0x22, 0x32, 0xF6])
def test_outer_control_commands_refused(opcode):
    frame = bytearray(packet("request"))
    frame[35] = opcode
    frame = rechecksum(frame)
    validate_outer(frame)
    with pytest.raises(ProtocolError, match="not an allowed"):
        validate_tx(frame)


@pytest.mark.parametrize("opcode", [0x82, 0x84, 0x85])
def test_inner_settings_and_controls_refused(opcode):
    frame = bytearray(packet("request"))
    frame[52] = opcode
    frame = rechecksum(frame, inner=True)
    validate_outer(frame)
    validate_inner(frame[39:-2], b"\x55\xaa")
    with pytest.raises(ProtocolError, match="not an allowed"):
        validate_tx(frame)


@pytest.mark.parametrize("size", [1, 20, 133, 244, 512, 1000])
def test_fragmentation_and_coalescing(size):
    expected = [packet("hello_reply"), packet("response")]
    raw = b"garbage" + b"".join(expected)
    assembler = FrameAssembler()
    result = []
    for pos in range(0, len(raw), size):
        result.extend(assembler.feed(raw[pos : pos + size]))
    assert result == expected
    assert not assembler.buffer


def test_damaged_frame_resynchronizes():
    good = packet("response")
    bad = bytearray(good)
    bad[70] ^= 1
    assembler = FrameAssembler()
    assert assembler.feed(bytes(bad) + good) == [good]
    assert assembler.invalid_frames == 1


def test_decoding_and_signed_temperature():
    frame = packet("response")
    value = decode_telemetry(frame, IDENTIFIER, bytes.fromhex("00000003"))
    assert (value.battery_level, value.battery_voltage, value.battery_temperature) == (89, 53.4, 23)
    assert (value.output_power, value.ac_output_power) == (381, 381)
    assert (value.ac_enabled, value.dc_enabled, value.usb_enabled) == (True, False, False)
    changed = bytearray(frame)
    # Main register data begins after inner header + block count/header.
    struct.pack_into("<h", changed, 59 + 60, -5)
    struct.pack_into("<H", changed, 59 + 82, 123)
    result = decode_telemetry(rechecksum(changed, inner=True), IDENTIFIER, frame[48:52])
    assert result.battery_temperature == -5
    assert result.usb_a_output_power == 12.3
    assert result.output_power == 393.3


@pytest.mark.parametrize(
    "kind", ["identity", "inner_sequence", "inner_checksum", "status", "soc", "block_length"]
)
def test_invalid_responses_refused(kind):
    frame = bytearray(packet("response"))
    if kind == "identity":
        frame[10] ^= 1
    elif kind == "inner_sequence":
        frame[48] ^= 1
    elif kind == "inner_checksum":
        frame[-4] ^= 1
    elif kind == "status":
        frame[37] = 1
    elif kind == "soc":
        struct.pack_into("<H", frame, 59 + 62, 101)
    else:
        struct.pack_into("<H", frame, 57, 299)
    frame = rechecksum(frame, inner=kind != "inner_checksum")
    with pytest.raises(ProtocolError):
        decode_telemetry(frame, IDENTIFIER, bytes.fromhex("00000003"))
