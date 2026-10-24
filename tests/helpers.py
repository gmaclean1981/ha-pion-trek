"""A fake BLE peripheral implementing only the observed read-only exchange."""

import json
import struct
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from bleak import BleakError

from custom_components.pion_trek.protocol import crc16, fingerprint

FIXTURE = json.loads((Path(__file__).parent / "fixtures/session.json").read_text())
IDENTIFIER = bytes.fromhex(FIXTURE["identifier"])
FINGERPRINT = fingerprint(IDENTIFIER)
CLOCK = datetime.fromisoformat(FIXTURE["clock"])
ADDRESS = "AA:BB:CC:DD:EE:FF"


def packet(name):
    return bytes.fromhex(FIXTURE[name])


def rechecksum(frame, *, inner=False):
    result = bytearray(frame)
    if inner:
        offset = 40 if result[35] == 0x31 else 39
        result[-4:-2] = struct.pack("<H", sum(result[offset:-4]) & 65535)
    result[-2:] = struct.pack("<H", crc16(result[2:-2]))
    return bytes(result)


class FakeBleak:
    def __init__(self, *, mtu=517, fail_read=False, stale_reply=False):
        self.is_connected = True
        self.mtu_size = mtu
        self.fail_read = fail_read
        self.stale_reply = stale_reply
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
        elif data[35] == 0x30:
            if self.fail_read:
                raise BleakError("Synthetic transport failure")
            reply = bytearray(packet("response"))
            reply[4:8] = data[4:8]
            reply[48:52] = data[47:51]
            if self.stale_reply:
                stale = bytearray(reply)
                stale[48:52] = bytes(4)
                self._emit(rechecksum(stale, inner=True))
            self._emit(rechecksum(reply, inner=True))

    async def disconnect(self):
        self.disconnected = True
        self.is_connected = False
