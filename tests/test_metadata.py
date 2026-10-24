"""Metadata is optional and must not compromise the existing telemetry path."""

import struct

import pytest

from custom_components.pion_trek.protocol import decode_telemetry

from .helpers import IDENTIFIER, SERIAL, metadata_packet, packet


def decode(overrides=None):
    frame = metadata_packet(overrides)
    return decode_telemetry(frame, IDENTIFIER, frame[48:52])


def test_metadata_formats_and_offsets():
    value = decode()
    assert value.serial_number == SERIAL
    assert SERIAL not in repr(value)
    assert value.hardware_version == "0.0.2.3"
    assert value.reported_software_version == "0.0.0.9"
    assert value.communications_firmware == "1.2.3.4"
    assert value.dsp_firmware == "01.1a"  # App displays hex, not decimal 1.26.
    assert value.bms_firmware == "V9.87"
    assert value.battery_health == 97
    assert [getattr(value, f"internal_temperature_{i}") for i in range(1, 6)] == [
        31,
        32,
        33,
        34,
        35,
    ]
    assert (value.battery_level, value.battery_temperature, value.ac_output_power) == (89, 23, 381)


@pytest.mark.parametrize("serial", [bytes(25), b" " * 25, b"X" * 25, b"\xff" * 25])
def test_missing_or_mismatched_serial_does_not_break_telemetry(serial):
    value = decode({1: serial})
    assert value.serial_number is None
    assert value.battery_level == 89
    assert value.ac_enabled


@pytest.mark.parametrize("serial", [bytes(25), b" " * 25, b"\xff" * 25, b"A\n" + b"B" * 23])
def test_even_matching_serial_must_be_printable(serial):
    from .helpers import rechecksum

    frame = bytearray(metadata_packet({1: serial}))
    frame[10:35] = serial
    value = decode_telemetry(rechecksum(frame), serial, frame[48:52])
    assert value.serial_number is None


@pytest.mark.parametrize(
    ("offset", "width", "key"),
    [
        (152, 4, "reported_software_version"),
        (156, 4, "hardware_version"),
        (160, 2, "dsp_firmware"),
        (269, 4, "communications_firmware"),
    ],
)
@pytest.mark.parametrize("fill", [0, 255])
def test_unset_versions_are_unknown(offset, width, key, fill):
    value = decode({offset: bytes([fill]) * width})
    assert getattr(value, key) is None
    assert value.battery_level == 89


@pytest.mark.parametrize(
    "text", [bytes(8), b" " * 8, b"\xff" * 8, b"V1\n\0\0\0\0\0", b"V1\0V2\0\0\0"]
)
def test_bad_bms_text_is_unknown(text):
    value = decode({273: text})
    assert value.bms_firmware is None
    assert value.battery_health == 97


@pytest.mark.parametrize("health", [0, 100, 101, 65535])
def test_battery_health_range(health):
    value = decode({64: struct.pack("<H", health)})
    assert value.battery_health == (health if health <= 100 else None)
    assert value.battery_level == 89


def test_unsigned_temperatures_zero_and_invalid_value():
    value = decode({145: bytes([0, 127, 128, 200, 255])})
    assert [getattr(value, f"internal_temperature_{i}") for i in range(1, 6)] == [
        0,
        127,
        128,
        200,
        None,
    ]


def test_older_fixture_without_identifying_metadata_still_decodes():
    frame = packet("response")
    value = decode_telemetry(frame, IDENTIFIER, frame[48:52])
    assert value.serial_number is None
    assert value.hardware_version is None
    assert value.communications_firmware is None
    assert value.battery_level == 89
