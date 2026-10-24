"""Fixed settings query and a write restricted to the maximum-charge register."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .protocol import OutputControlProtocol, ProtocolError, u16, validate_inner, validate_outer

SETTINGS_BODY = bytes.fromhex("0710A4640064B202006AB202006EB2010069B2010070B2010066B20200")
SETTINGS_BLOCKS = {42000: 100, 45668: 2, 45674: 2, 45678: 1, 45673: 1, 45680: 1, 45670: 2}
MAX_CHARGE_REGISTER = 42059


def validate_charge_limit(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 100:
        raise ProtocolError("Maximum charge must be a whole percentage from 0 to 100")


def charge_body(value: int) -> bytes:
    validate_charge_limit(value)
    return b"\x01" + struct.pack("<HHB", MAX_CHARGE_REGISTER, 1, value)


class ChargeControlProtocol(OutputControlProtocol):
    def _charge_frame(self, outer_opcode: int, inner_opcode: int, body: bytes) -> bytes:
        inner = (
            b"\x55\xaa"
            + struct.pack("<H", 14 + len(body))
            + b"\x01\x01\x02\x08"
            + self._next_sequence()
            + bytes([2, inner_opcode])
            + body
        )
        inner += struct.pack("<H", sum(inner) & 0xFFFF)
        return self._outer(outer_opcode, b"\x03" + struct.pack("<H", len(inner)) + inner)

    def settings(self) -> bytes:
        return self._charge_frame(0x30, 0x82, SETTINGS_BODY)

    def set_charge_limit(self, value: int) -> bytes:
        # Validate before advancing sequence or preparing a packet.
        return self._charge_frame(0x32, 0x84, charge_body(value))


def _validate_request(frame: bytes, opcode: int, command: int, body: bytes) -> None:
    validate_outer(frame)
    inner = frame[39:-2]
    validate_inner(inner, b"\x55\xaa")
    if (
        frame[8:10] != b"\x04\x01"
        or frame[35:37] != bytes([opcode, 3])
        or u16(frame[37:39]) != len(inner)
        or inner[4:8] != b"\x01\x01\x02\x08"
        or inner[12:14] != bytes([2, command])
        or inner[14:-2] != body
    ):
        raise ProtocolError("Not an allowed charge-limit request")


def validate_settings_query(frame: bytes) -> None:
    _validate_request(frame, 0x30, 0x82, SETTINGS_BODY)


def validate_charge_tx(frame: bytes) -> None:
    if len(frame) != 63:
        raise ProtocolError("Not a single charge-limit write")
    _validate_request(frame, 0x32, 0x84, charge_body(frame[58]))


def _response_body(
    frame: bytes, identifier: bytes, outer_sequence: bytes, inner_sequence: bytes, command: int
) -> bytes:
    validate_outer(frame)
    if (
        frame[8:10] != b"\x03\x01"
        or frame[10:35] != identifier
        or frame[4:8] != outer_sequence
        or frame[35:38] != b"\x33\x03\x00"
    ):
        raise ProtocolError("Unexpected charge-limit response")
    inner = frame[40:-2]
    validate_inner(inner, b"\xaa\x55")
    if (
        u16(frame[38:40]) != len(inner)
        or inner[4:8] != b"\x00\x01\x00\x0a"
        or inner[8:12] != inner_sequence
        or inner[12:14] != bytes([3, command])
    ):
        raise ProtocolError("Charge-limit response command or sequence mismatch")
    return inner[14:-2]


@dataclass(frozen=True)
class ChargeSettings:
    # Settings can contain identifying data. Never include raw blocks in repr/logs.
    blocks: tuple[tuple[int, bytes], ...] = field(repr=False)
    max_charge_limit: int
    min_charge_limit: int

    def other_settings(self) -> tuple[tuple[int, bytes], ...]:
        """Compare readback without the one byte we intentionally changed."""
        return tuple(
            (address, data[:59] + b"\0" + data[60:] if address == 42000 else data)
            for address, data in self.blocks
        )


def decode_settings(
    frame: bytes, identifier: bytes, outer_sequence: bytes, inner_sequence: bytes
) -> ChargeSettings:
    body = _response_body(frame, identifier, outer_sequence, inner_sequence, 0x82)
    if not body or body[0] != len(SETTINGS_BLOCKS):
        raise ProtocolError("Unsupported settings block count")
    blocks = {}
    pos = 1
    for _ in range(body[0]):
        if pos + 4 > len(body):
            raise ProtocolError("Truncated settings header")
        address, length = struct.unpack_from("<HH", body, pos)
        pos += 4
        if address in blocks or SETTINGS_BLOCKS.get(address) != length or pos + length > len(body):
            raise ProtocolError("Unsupported or truncated settings block")
        blocks[address] = body[pos : pos + length]
        pos += length
    if pos != len(body):
        raise ProtocolError("Unexpected settings data")
    maximum, minimum = blocks[42000][59:61]
    if maximum > 100 or minimum > 100:
        raise ProtocolError("Invalid charge-limit percentage")
    return ChargeSettings(tuple(sorted(blocks.items())), maximum, minimum)


def validate_charge_ack(
    frame: bytes, identifier: bytes, outer_sequence: bytes, inner_sequence: bytes, value: int
) -> None:
    body = _response_body(frame, identifier, outer_sequence, inner_sequence, 0x84)
    if body != charge_body(value):
        raise ProtocolError("Charge-limit acknowledgement does not match the request")
