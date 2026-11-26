#!/usr/bin/env python3
"""Низкоуровневый protobuf parser с сохранением исходных байтов."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterator


WT_VARINT = 0
WT_64BIT = 1
WT_LEN = 2
WT_32BIT = 5

UINT64_MAX = (1 << 64) - 1
INT64_MAX = (1 << 63) - 1

STATUS_DECODED = "decoded"
STATUS_EMPTY = "empty"
STATUS_INVALID = "invalid"
STATUS_OPAQUE = "opaque"


@dataclass(frozen=True)
class Field:
    number: int
    wire_type: int
    value: int | bytes
    raw_value: bytes
    offset: int
    raw_bytes: bytes

    @property
    def key(self) -> int:
        return (self.number << 3) | self.wire_type


def read_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Читает uint64 varint. Возвращает значение и число байтов."""
    if offset < 0 or offset >= len(data):
        raise ValueError("Varint отсутствует или смещение вне данных")

    result = 0

    for index in range(10):
        pos = offset + index

        if pos >= len(data):
            raise ValueError("Обрезанный varint")

        byte = data[pos]

        if index == 9 and byte > 1:
            raise ValueError("Varint превышает uint64")

        result |= (byte & 0x7F) << (7 * index)

        if not (byte & 0x80):
            return result, index + 1

    raise ValueError("Varint длиннее 10 байтов")


def encode_varint(value: int) -> bytes:
    """Кодирует беззнаковый varint."""
    if not isinstance(value, int) or value < 0 or value > UINT64_MAX:
        raise ValueError("Значение вне диапазона uint64")

    result = bytearray()

    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7

    result.append(value)
    return bytes(result)


def iter_fields(data: bytes) -> Iterator[Field]:
    """Последовательно разбирает поля protobuf."""
    if not isinstance(data, bytes):
        raise TypeError("data должен иметь тип bytes")

    pos = 0
    size = len(data)

    while pos < size:
        start = pos

        key, key_size = read_varint(data, pos)
        pos += key_size

        number = key >> 3
        wire_type = key & 7

        if number == 0 or number > (1 << 29) - 1:
            raise ValueError(f"Недопустимый номер поля: {number}")

        value_start = pos

        if wire_type == WT_VARINT:
            value, value_size = read_varint(data, pos)
            pos += value_size
            raw_value = data[value_start:pos]

        elif wire_type == WT_64BIT:
            if pos + 8 > size:
                raise ValueError("Обрезанное fixed64 поле")
            raw_value = data[pos:pos + 8]
            value = raw_value
            pos += 8

        elif wire_type == WT_LEN:
            length, length_size = read_varint(data, pos)
            pos += length_size

            if length > size - pos:
                raise ValueError("Обрезанное LEN поле")

            raw_value = data[pos:pos + length]
            value = raw_value
            pos += length

        elif wire_type == WT_32BIT:
            if pos + 4 > size:
                raise ValueError("Обрезанное fixed32 поле")
            raw_value = data[pos:pos + 4]
            value = raw_value
            pos += 4

        else:
            raise ValueError(
                f"Неподдерживаемый wire type {wire_type} "
                f"у поля {number}, смещение {start}"
            )

        yield Field(
            number=number,
            wire_type=wire_type,
            value=value,
            raw_value=raw_value,
            offset=start,
            raw_bytes=data[start:pos],
        )


def collect_fields(data: bytes) -> dict[int, list[Field]]:
    """Собирает поля по номерам, сохраняя повторения."""
    result: dict[int, list[Field]] = {}

    for field in iter_fields(data):
        result.setdefault(field.number, []).append(field)

    return result


def rebuild_message(fields: list[Field]) -> bytes:
    """Восстанавливает сообщение из исходных байтов полей."""
    ordered = sorted(fields, key=lambda item: item.offset)
    return b"".join(field.raw_bytes for field in ordered)


def first_varint(fields: dict[int, list[Field]], number: int):
    """Возвращает первое varint-значение или None."""
    for field in fields.get(number, []):
        if field.wire_type == WT_VARINT:
            return int(field.value)
    return None


def first_varint_raw(fields: dict[int, list[Field]], number: int):
    """Возвращает первое varint как пару (значение, исходные байты)."""
    for field in fields.get(number, []):
        if field.wire_type == WT_VARINT:
            return int(field.value), field.raw_value
    return None


def first_fixed32(fields: dict[int, list[Field]], number: int):
    """Возвращает первое fixed32 поле как число float."""
    for field in fields.get(number, []):
        if field.wire_type == WT_32BIT:
            return struct.unpack("<f", field.raw_value)[0]
    return None


def bytes_fields(fields: dict[int, list[Field]], number: int) -> list[bytes]:
    """Возвращает все LEN-поля с указанным номером."""
    return [
        bytes(field.raw_value)
        for field in fields.get(number, [])
        if field.wire_type == WT_LEN
    ]


def zigzag_decode(value: int) -> int:
    """Декодирует ZigZag integer."""
    return (value >> 1) ^ -(value & 1)


def int64_decode(value: int) -> int:
    """Интерпретирует uint64 как signed int64."""
    value &= UINT64_MAX
    return value - (1 << 64) if value > INT64_MAX else value