"""Additional read-only fields match the app's offsets and unsigned scaling."""

import struct

import pytest

from custom_components.pion_trek.protocol import decode_telemetry

from .helpers import IDENTIFIER, metadata_packet

# Constructed values, distinct for every field to detect swapped offsets.
READINGS = (
    ("ac_input_voltage", 28, 1197, 119.7),
    ("ac_input_frequency", 32, 599, 59.9),
    ("inverter_voltage", 42, 1213, 121.3),
    ("inverter_frequency", 46, 601, 60.1),
    ("battery_cell_temperature_max", 76, 286, 28.6),
    ("battery_cell_temperature_min", 78, 254, 25.4),
    ("dc_barrel_output_power", 86, 123, 12.3),
    ("dc_rv_output_power", 88, 456, 45.6),
    ("dc_car_output_power", 260, 789, 78.9),
)


def decoded(overrides):
    frame = metadata_packet(overrides)
    return decode_telemetry(frame, IDENTIFIER, frame[48:52])


def test_distinct_electrical_fields_and_total_output_are_not_double_counted():
    value = decoded({offset: struct.pack("<H", raw) for _, offset, raw, _ in READINGS})
    for key, _, _, expected in READINGS:
        assert getattr(value, key) == expected
    assert value.output_power == 517.8  # 381 AC + 12.3 + 45.6 + 78.9 DC
    assert value.ac_output_power == 381
    assert value.battery_temperature == 23
    assert value.battery_level == 89


@pytest.mark.parametrize(("key", "offset", "raw", "expected"), READINGS)
@pytest.mark.parametrize("replacement", [0, 65535])
def test_zero_is_valid_and_all_ff_is_unknown_without_losing_other_fields(
    key, offset, raw, expected, replacement
):
    overrides = {o: struct.pack("<H", v) for _, o, v, _ in READINGS}
    overrides[offset] = struct.pack("<H", replacement)
    value = decoded(overrides)
    assert getattr(value, key) == (0.0 if replacement == 0 else None)
    for other, _, _, other_expected in READINGS:
        if other != key:
            assert getattr(value, other) == other_expected
    assert value.ac_enabled
    assert value.battery_level == 89
