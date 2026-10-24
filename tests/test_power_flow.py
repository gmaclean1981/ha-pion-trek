"""Power-flow decoding preserves signed app values and handles unknown states."""

import struct

import pytest

from custom_components.pion_trek.protocol import decode_telemetry

from .helpers import IDENTIFIER, metadata_packet

READINGS = (
    ("ac_input_current", 30, 47, 4.7),
    ("ac_input_power", 34, 523, 523),
    ("battery_current", 56, -32, -3.2),
    ("battery_power", 58, -169, -169),
)


def decoded(overrides):
    frame = metadata_packet(overrides)
    return decode_telemetry(frame, IDENTIFIER, frame[48:52])


def test_distinct_power_flow_fields_do_not_change_output_total():
    value = decoded({offset: struct.pack("<h", raw) for _, offset, raw, _ in READINGS})
    for key, _, _, expected in READINGS:
        assert getattr(value, key) == expected
    assert value.output_power == 381.0
    assert value.ac_output_power == 381
    assert value.battery_level == 89


@pytest.mark.parametrize(("key", "offset", "raw", "expected"), READINGS)
@pytest.mark.parametrize("replacement", [-32768, -321, -1, 0, 123, 32767])
def test_signed_values_including_all_ff_are_not_clipped(key, offset, raw, expected, replacement):
    value = decoded({offset: struct.pack("<h", replacement)})
    scale = 10 if key.endswith("current") else 1
    assert getattr(value, key) == replacement / scale
    assert value.ac_enabled


@pytest.mark.parametrize(
    ("code", "expected"),
    [(0, "idle"), (1, "charging"), (2, "discharging"), (3, None), (254, None), (255, None)],
)
def test_main_unit_status_and_unknown_codes_do_not_invalidate_telemetry(code, expected):
    value = decoded({97: bytes([code])})
    assert value.charging_status == expected
    assert value.charging_status_code == code
    assert value.output_power == 381.0
    assert value.battery_level == 89


def test_reconstructed_battery_only_trial_uses_register_parser_status_mapping():
    # Constructed packet using values observed in HA, not a raw captured packet.
    value = decoded(
        {
            28: struct.pack("<H", 0),
            30: struct.pack("<h", 0),
            34: struct.pack("<h", 0),
            56: struct.pack("<h", 83),
            58: struct.pack("<h", 440),
            80: struct.pack("<H", 395),
            97: b"\x02",
        }
    )
    assert value.ac_input_voltage == 0
    assert value.ac_input_current == 0
    assert value.battery_current == 8.3
    assert value.battery_power == 440
    assert value.charging_status == "discharging"
    assert value.charging_status_code == 2
    assert value.output_power == 395
