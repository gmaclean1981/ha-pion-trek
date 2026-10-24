"""A fake BLE peripheral implementing captured telemetry and output exchanges."""

import json
import struct
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from bleak import BleakError

from custom_components.pion_trek.protocol import crc16, fingerprint

FIXTURE = json.loads((Path(__file__).parent / "fixtures/session.json").read_text())
OUTPUT_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/output_acknowledgements.json").read_text()
)
SETTINGS_FIXTURE = json.loads((Path(__file__).parent / "fixtures/settings.json").read_text())
CHARGE_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/charge_acknowledgements.json").read_text()
)
IDENTIFIER = bytes.fromhex(FIXTURE["identifier"])
FINGERPRINT = fingerprint(IDENTIFIER)
CLOCK = datetime.fromisoformat(FIXTURE["clock"])
ADDRESS = "AA:BB:CC:DD:EE:FF"
SERIAL = IDENTIFIER.decode("ascii")

# Fabricated metadata, deliberately distinct from the owner's device.
METADATA = {
    1: IDENTIFIER,
    64: struct.pack("<H", 97),
    145: bytes([31, 32, 33, 34, 35]),
    152: bytes([0, 0, 0, 9]),
    156: bytes([0, 0, 2, 3]),
    160: bytes([1, 0x1A]),
    269: bytes([1, 2, 3, 4]),
    273: b"V9.87\0\0\0",
}


def packet(name):
    return bytes.fromhex(FIXTURE[name])


def rechecksum(frame, *, inner=False):
    result = bytearray(frame)
    if inner:
        offset = 40 if result[35] in (0x31, 0x33) else 39
        result[-4:-2] = struct.pack("<H", sum(result[offset:-4]) & 65535)
    result[-2:] = struct.pack("<H", crc16(result[2:-2]))
    return bytes(result)


def metadata_packet(overrides=None):
    """Construct a valid response with fabricated metadata and optional mutations."""
    frame = bytearray(packet("response"))
    for offset, value in (METADATA | (overrides or {})).items():
        frame[59 + offset : 59 + offset + len(value)] = value
    return rechecksum(frame, inner=True)


class FakeBleak:
    def __init__(self, *, mtu=517, fail_read=False, stale_reply=False):
        self.is_connected = True
        self.mtu_size = mtu
        self.fail_read = fail_read
        self.stale_reply = stale_reply
        self.output_states = {"ac": True, "dc": False, "usb": False}
        self.control_mode = "normal"
        self.control_delay_reads = 0
        self.pending_output = None
        self.metadata_overrides = {}
        self.max_charge_limit = 90
        self.min_charge_limit = 3
        self.charge_mode = "normal"
        self.charge_delay_reads = 0
        self.pending_charge_limit = None
        self.other_setting = 100
        self.fail_settings = False
        self.writes = []
        self.disconnected = False
        self.notify = None
        self.char = SimpleNamespace(properties=["read", "write", "notify"])
        service = SimpleNamespace(get_characteristic=lambda _: self.char)
        self.services = SimpleNamespace(get_service=lambda _: service)

    async def start_notify(self, char, callback):
        self.notify = callback

    def _emit(self, frame):
        # A real proxy may split a 397-byte response across notifications.
        self.notify(self.char, bytearray(frame[:133]))
        self.notify(self.char, bytearray(frame[133:]))

    async def write_gatt_char(self, char, data, response):
        assert response is True
        self.writes.append(bytes(data))
        if data[35] == 4:
            reply = bytearray(packet("hello_reply"))
            reply[4:8] = data[4:8]
            self._emit(rechecksum(reply))
        elif data[35] == 0x32:
            assert data[52] == 0x84 and data[53:58] == bytes.fromhex("014ba40100")
            if self.charge_mode not in ("reject", "no_change"):
                if self.charge_delay_reads:
                    self.pending_charge_limit = data[58]
                else:
                    self.max_charge_limit = data[58]
            if self.charge_mode == "other_setting":
                self.other_setting = 99
            if self.charge_mode == "output_changed":
                self.output_states["ac"] = False
            if self.charge_mode == "write_error":
                raise BleakError("Synthetic ambiguous settings write failure")
            if self.charge_mode == "drop_ack":
                return
            # Layout from the verified single-register trial, identifiers fabricated.
            reply = bytearray.fromhex(CHARGE_FIXTURES["cases"][0]["reply_hex"])
            reply[4:8], reply[48:52] = data[4:8], data[47:51]
            reply[53:60] = bytes([0x84, 1]) + struct.pack("<HHB", 42059, 1, data[58])
            if self.charge_mode == "reject":
                reply[37] = 1
            if self.charge_mode == "wrong_value":
                reply[59] ^= 1
            self._emit(rechecksum(reply, inner=True))
        elif data[35] == 0x30:
            if data[52] == 0x82:
                if self.fail_settings:
                    raise BleakError("Synthetic settings read failure")
                if self.pending_charge_limit is not None:
                    if self.charge_delay_reads:
                        self.charge_delay_reads -= 1
                    else:
                        self.max_charge_limit = self.pending_charge_limit
                        self.pending_charge_limit = None
                reply = bytearray.fromhex(SETTINGS_FIXTURE["reply"])
                reply[4:8], reply[48:52] = data[4:8], data[47:51]
                reply[118:121] = bytes(
                    [self.max_charge_limit, self.min_charge_limit, self.other_setting]
                )
                if self.stale_reply:
                    stale = bytearray(reply)
                    stale[48:52] = bytes(4)
                    self._emit(rechecksum(stale, inner=True))
                self._emit(rechecksum(reply, inner=True))
                return
            if data[52] == 0x85:
                output = {42001: "ac", 42002: "dc", 42003: "usb"}[
                    int.from_bytes(data[54:56], "little")
                ]
                enabled = bool(data[58])
                if self.control_mode not in ("reject", "no_change"):
                    if self.control_delay_reads:
                        self.pending_output = (output, enabled)
                    else:
                        self.output_states[output] = enabled
                if self.control_mode == "write_error":
                    raise BleakError("Synthetic ambiguous write failure")
                if self.control_mode == "drop_ack":
                    return
                case = next(
                    case
                    for case in OUTPUT_FIXTURES["cases"]
                    if case["output"] == output and case["enabled"] == enabled
                )
                reply = bytearray.fromhex(case["reply_hex"])
                reply[4:8], reply[48:52] = data[4:8], data[47:51]
                if self.control_mode == "reject":
                    reply[37] = 1
                if self.control_mode == "wrong_value":
                    reply[59] = 1 - reply[59]
                if self.stale_reply:
                    stale = bytearray(reply)
                    stale[48:52] = bytes(4)
                    self._emit(rechecksum(stale, inner=True))
                self._emit(rechecksum(reply, inner=True))
                return
            if self.fail_read:
                raise BleakError("Synthetic transport failure")
            if self.pending_output is not None:
                if self.control_delay_reads:
                    self.control_delay_reads -= 1
                else:
                    output, enabled = self.pending_output
                    self.output_states[output] = enabled
                    self.pending_output = None
            reply = bytearray(metadata_packet(self.metadata_overrides))
            reply[4:8] = data[4:8]
            reply[48:52] = data[47:51]
            reply[151:154] = bytes(self.output_states[key] for key in ("ac", "dc", "usb"))
            if self.stale_reply:
                stale = bytearray(reply)
                stale[48:52] = bytes(4)
                self._emit(rechecksum(stale, inner=True))
            self._emit(rechecksum(reply, inner=True))

    async def disconnect(self):
        self.disconnected = True
        self.is_connected = False
