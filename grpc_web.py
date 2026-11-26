#!/usr/bin/env python3
"""Разбор кадров gRPC-Web."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GrpcWebFrame:
    flag: int
    length: int
    payload: bytes

    @property
    def is_trailer(self) -> bool:
        return bool(self.flag & 0x80)

    @property
    def is_data(self) -> bool:
        return not self.is_trailer

    @property
    def is_compressed(self) -> bool:
        return bool(self.flag & 0x01)


def decode_grpc_web_body(data: bytes) -> list[GrpcWebFrame]:
    """Разбирает последовательность gRPC-Web кадров."""
    if not isinstance(data, bytes):
        raise TypeError("data должен иметь тип bytes")

    frames = []
    pos = 0

    while pos < len(data):
        if len(data) - pos < 5:
            raise ValueError(
                f"Обрезан заголовок кадра: смещение {pos}"
            )

        flag = data[pos]
        length = int.from_bytes(data[pos + 1:pos + 5], "big")
        pos += 5

        if flag not in (0x00, 0x01, 0x80, 0x81):
            raise ValueError(
                f"Неизвестный флаг gRPC-Web: 0x{flag:02x}"
            )

        if length > len(data) - pos:
            raise ValueError(
                f"Обрезан payload кадра: заявлено {length}, "
                f"доступно {len(data) - pos}"
            )

        payload = data[pos:pos + length]
        pos += length

        frames.append(
            GrpcWebFrame(
                flag=flag,
                length=length,
                payload=payload,
            )
        )

    return frames