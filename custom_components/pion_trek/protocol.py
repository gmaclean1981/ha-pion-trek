"""Small implementation of the observed FSpower T4 protocol.

Telemetry and single-output boolean commands were validated on a Trek 4200.
No generic settings, charging configuration or firmware writer is provided.
This module has no network or Home Assistant imports.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from datetime import datetime

SERVICE_UUID = "000000ff-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
READ_BODY = bytes.fromhex("07C8322C01F43301001E34020022340200BC340100E6340200EA340200")
OUTPUT_REGISTERS = {"ac": 42001, "dc": 42002, "usb": 42003}


class ProtocolError(ValueError):
    """An unexpected or damaged protocol message."""


def u16(data: bytes | bytearray) -> int:
    return int.from_bytes(data, "little")


def crc16(data: bytes | bytearray) -> int:
    """CRC-16/MODBUS, excluding outer magic and checksum."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def validate_outer(frame: bytes) -> None:
    if len(frame) < 38 or frame[:2] != b"\xa5\x5a":
        raise ProtocolError("Invalid frame header")
    if u16(frame[2:4]) != len(frame):
        raise ProtocolError("Frame length mismatch")
    if u16(frame[-2:]) != crc16(frame[2:-2]):
        raise ProtocolError("Frame CRC mismatch")


def validate_inner(inner: bytes, magic: bytes) -> None:
    if len(inner) < 16 or inner[:2] != magic:
        raise ProtocolError("Invalid inner header")
    if u16(inner[2:4]) + 2 != len(inner):
        raise ProtocolError("Inner length mismatch")
    if u16(inner[-2:]) != sum(inner[:-2]) & 0xFFFF:
        raise ProtocolError("Inner checksum mismatch")


def fingerprint(identifier: bytes) -> str:
    return hashlib.sha256(identifier).hexdigest()


class ReadOnlyProtocol:
    """Encode only the observed session handshake and telemetry request."""

    def __init__(self) -> None:
        self.identifier = bytes(25)
        self.sequence = 0

    def _next_sequence(self) -> bytes:
        # The app encodes eight DECIMAL digits as hexadecimal byte pairs.
        self.sequence = self.sequence % 99999999 + 1
        return bytes.fromhex(f"{self.sequence:08d}")

    def _outer(self, opcode: int, payload: bytes) -> bytes:
        body = (
            struct.pack("<H", 38 + len(payload))
            + self._next_sequence()
            + b"\x04\x01"
            + self.identifier
            + bytes([opcode])
            + payload
        )
        return b"\xa5\x5a" + body + struct.pack("<H", crc16(body))

    @staticmethod
    def _clock(now: datetime) -> bytes:
        return bytes([now.year - 2022, now.month, now.day, now.hour, now.minute, now.second])

    def hello(self, now: datetime) -> bytes:
        return self._outer(4, b"\x01\x01" + self._clock(now) + b"\x03")

    def platform(self, now: datetime) -> bytes:
        return self._outer(2, b"2.0\0\0\0" + self._clock(now))

    def telemetry(self) -> bytes:
        inner = (
            b"\x55\xaa"
            + struct.pack("<H", 14 + len(READ_BODY))
            + b"\x01\x01\x02\x08"
            + self._next_sequence()
            + b"\x02\x80"
            + READ_BODY
        )
        inner += struct.pack("<H", sum(inner) & 0xFFFF)
        return self._outer(0x30, b"\x03" + struct.pack("<H", len(inner)) + inner)


class OutputControlProtocol(ReadOnlyProtocol):
    """Encode a single requested output state; no generic settings writer."""

    def set_output(self, output: str, enabled: bool) -> bytes:
        body = output_command_body(output, enabled)
        inner = (
            b"\x55\xaa"
            + struct.pack("<H", 14 + len(body))
            + b"\x01\x01\x02\x08"
            + self._next_sequence()
            + b"\x02\x85"
            + body
        )
        inner += struct.pack("<H", sum(inner) & 0xFFFF)
        return self._outer(0x30, b"\x03" + struct.pack("<H", len(inner)) + inner)


def output_command_body(output: str, enabled: bool) -> bytes:
    """Validate the narrow public command arguments before any I/O."""
    if type(output) is not str or output not in OUTPUT_REGISTERS:
        raise ProtocolError("Unsupported output")
    if type(enabled) is not bool:
        raise ProtocolError("Output state must be a boolean")
    return b"\x01" + struct.pack("<HHB", OUTPUT_REGISTERS[output], 1, enabled)


def validate_output_tx(frame: bytes) -> None:
    """Allow exactly one AC/DC/USB boolean write, independently of its encoder."""
    validate_outer(frame)
    if len(frame) != 63 or frame[8:10] != b"\x04\x01" or frame[35:39] != b"\x30\x03\x16\x00":
        raise ProtocolError("Not an allowed output command")
    inner = frame[39:-2]
    validate_inner(inner, b"\x55\xaa")
    if (
        inner[4:8] != b"\x01\x01\x02\x08"
        or inner[12:15] != b"\x02\x85\x01"
        or u16(inner[15:17]) not in OUTPUT_REGISTERS.values()
        or inner[17:19] != b"\x01\x00"
        or inner[19] not in (0, 1)
    ):
        raise ProtocolError("Not an allowed output command")


def validate_output_ack(
    frame: bytes,
    identifier: bytes,
    outer_sequence: bytes,
    inner_sequence: bytes,
    output: str,
    enabled: bool,
) -> None:
    """Match the captured 0x33 acknowledgement; telemetry still confirms state."""
    expected_body = output_command_body(output, enabled)
    validate_outer(frame)
    if (
        len(frame) != 64
        or frame[8:10] != b"\x03\x01"
        or frame[10:35] != identifier
        or frame[4:8] != outer_sequence
        or frame[35:40] != b"\x33\x03\x00\x16\x00"
    ):
        raise ProtocolError("Unexpected output acknowledgement")
    inner = frame[40:-2]
    validate_inner(inner, b"\xaa\x55")
    if (
        inner[4:8] != b"\x00\x01\x00\x0a"
        or inner[8:12] != inner_sequence
        or inner[12:14] != b"\x03\x85"
        or inner[14:-2] != expected_body
    ):
        raise ProtocolError("Output acknowledgement does not match the requested state")


def validate_tx(frame: bytes) -> None:
    """Enforce the read-only boundary again immediately before transmission."""
    validate_outer(frame)
    payload = frame[36:-2]
    if frame[8:10] != b"\x04\x01":
        raise ProtocolError("Unexpected request header")
    if frame[35] == 4 and len(payload) == 9 and payload[:2] == b"\x01\x01" and payload[-1] == 3:
        return
    if frame[35] == 2 and len(payload) == 12 and payload[:6] == b"2.0\0\0\0":
        return
    if frame[35] == 0x30 and payload[:3] == b"\x03\x2d\x00":
        inner = payload[3:]
        validate_inner(inner, b"\x55\xaa")
        if (
            inner[4:8] == b"\x01\x01\x02\x08"
            and inner[12:14] == b"\x02\x80"
            and inner[14:-2] == READ_BODY
        ):
            return
    raise ProtocolError("Transmission is not an allowed session/telemetry request")


class FrameAssembler:
    """Reassemble notifications, including fragmented and coalesced frames."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.invalid_frames = 0

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            start = self.buffer.find(b"\xa5\x5a")
            if start < 0:
                self.buffer[:] = b"\xa5" if self.buffer[-1:] == b"\xa5" else b""
                break
            del self.buffer[:start]
            if len(self.buffer) < 4:
                break
            size = u16(self.buffer[2:4])
            if size < 38 or size > 4096:
                self.invalid_frames += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < size:
                break
            frame = bytes(self.buffer[:size])
            try:
                validate_outer(frame)
            except ProtocolError:
                self.invalid_frames += 1
                del self.buffer[0]
                continue
            del self.buffer[:size]
            frames.append(frame)
        return frames


@dataclass(frozen=True)
class Telemetry:
    battery_level: int
    battery_voltage: float
    battery_temperature: int
    output_power: float
    ac_output_power: int
    usb_a_output_power: float
    usb_c_output_power: float
    ac_enabled: bool
    dc_enabled: bool
    usb_enabled: bool
    serial_number: str | None = field(default=None, repr=False)
    hardware_version: str | None = None
    reported_software_version: str | None = None
    communications_firmware: str | None = None
    dsp_firmware: str | None = None
    bms_firmware: str | None = None
    battery_health: int | None = None
    internal_temperature_1: int | None = None
    internal_temperature_2: int | None = None
    internal_temperature_3: int | None = None
    internal_temperature_4: int | None = None
    internal_temperature_5: int | None = None
    # Filled by the client from its separate settings query, not block 13000.
    max_charge_limit: int | None = None
    min_charge_limit: int | None = None
    ac_charge_power_limit: int | None = None


def _text(data: bytes) -> str | None:
    """Accept printable ASCII with optional trailing NUL padding."""
    data = data.rstrip(b"\0")
    if not data or not any(byte != 32 for byte in data):
        return None
    if any(byte < 32 or byte > 126 for byte in data):
        return None
    return data.decode("ascii")


def _version(data: bytes, *, hexadecimal: bool = False) -> str | None:
    """Match the app's decimal versions and its distinct hexadecimal DSP version."""
    if data in (bytes(len(data)), b"\xff" * len(data)):
        return None
    return ".".join(f"{byte:02x}" if hexadecimal else str(byte) for byte in data)


def decode_telemetry(frame: bytes, identifier: bytes, inner_sequence: bytes) -> Telemetry:
    """Validate the response and decode only the deliberately exposed fields."""
    validate_outer(frame)
    if frame[35] != 0x31 or frame[10:35] != identifier or frame[36:38] != b"\x03\x00":
        raise ProtocolError("Unexpected telemetry response or device identity")
    inner = frame[40:-2]
    if u16(frame[38:40]) != len(inner):
        raise ProtocolError("Inner wrapper length mismatch")
    validate_inner(inner, b"\xaa\x55")
    if inner[13] != 0x80 or inner[8:12] != inner_sequence:
        raise ProtocolError("Unexpected telemetry command or sequence")
    body = inner[14:-2]
    if not body:
        raise ProtocolError("No telemetry blocks")
    blocks: dict[int, bytes] = {}
    pos = 1
    for _ in range(body[0]):
        if pos + 4 > len(body):
            raise ProtocolError("Truncated register header")
        address, length = struct.unpack_from("<HH", body, pos)
        pos += 4
        if pos + length > len(body) or address in blocks:
            raise ProtocolError("Truncated or duplicate register block")
        blocks[address] = body[pos : pos + length]
        pos += length
    if pos != len(body) or len(blocks.get(13000, b"")) != 300:
        raise ProtocolError("Unsupported telemetry layout")
    data = blocks[13000]
    soc = u16(data[62:64])
    if soc > 100 or any(value not in (0, 1) for value in data[92:95]):
        raise ProtocolError("Unsupported battery or output-state values")
    ac = u16(data[80:82])
    usb_a = u16(data[82:84]) / 10
    usb_c = u16(data[84:86]) / 10
    output = ac + sum(u16(data[o : o + 2]) / 10 for o in (82, 84, 86, 88, 260))
    return Telemetry(
        battery_level=soc,
        battery_voltage=u16(data[54:56]) / 10,
        battery_temperature=int.from_bytes(data[60:62], "little", signed=True),
        output_power=round(output, 1),
        ac_output_power=ac,
        usb_a_output_power=usb_a,
        usb_c_output_power=usb_c,
        ac_enabled=bool(data[92]),
        dc_enabled=bool(data[93]),
        usb_enabled=bool(data[94]),
        serial_number=_text(data[1:26]) if data[1:26] == identifier else None,
        hardware_version=_version(data[156:160]),
        reported_software_version=_version(data[152:156]),
        communications_firmware=_version(data[269:273]),
        dsp_firmware=_version(data[160:162], hexadecimal=True),
        bms_firmware=_text(data[273:281]),
        battery_health=u16(data[64:66]) if u16(data[64:66]) <= 100 else None,
        # The app uses unsigned bytes, unlike its signed main battery temperature.
        # Suppress 0xFF rather than presenting an implausible 255 degrees as valid.
        **{
            f"internal_temperature_{index}": value if value != 0xFF else None
            for index, value in enumerate(data[145:150], start=1)
        },
    )
