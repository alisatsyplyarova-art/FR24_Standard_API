#!/usr/bin/env python3
"""Модели данных FR24 Decoder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STATUS_DECODED = "decoded"
STATUS_EMPTY = "empty"
STATUS_INVALID = "invalid"
STATUS_OPAQUE = "opaque"


@dataclass(frozen=True)
class SourceRef:
    http_record_index: int
    frame_index: int
    protobuf_message_index: int


@dataclass
class LenNode:
    field_number: int
    field_index: int
    original_bytes: bytes
    status: str
    depth: int = 0
    fields: list[Any] = field(default_factory=list)
    nested: list["LenNode"] = field(default_factory=list)
    error: str | None = None


@dataclass
class TrackPoint:
    """Точка траектории в WGS84. Время в миллисекундах Unix."""
    latitude: float
    longitude: float
    timestamp: int | None
    source_frame: int
    raw_fields: dict = field(default_factory=dict)


@dataclass
class PositionSample:
    field_1: int | None = None
    field_2: int | None = None
    field_3: int | None = None
    all_fields: dict[int, list[Any]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    source: SourceRef | None = None


@dataclass
class PositionHistory:
    samples: list[PositionSample] = field(default_factory=list)
    all_fields: dict[int, list[Any]] = field(default_factory=dict)
    unknown_len: list[LenNode] = field(default_factory=list)
    source: SourceRef | None = None


@dataclass
class Feed:
    field_1: int | None = None
    field_2: float | None = None
    field_3: float | None = None
    field_5: int | None = None
    field_6: int | None = None
    field_9: int | None = None
    field_11: str | None = None
    field_12: int | None = None
    field_15: int | None = None

    histories: list[PositionHistory] = field(default_factory=list)
    track: list[TrackPoint] = field(default_factory=list)
    all_fields: dict[int, list[Any]] = field(default_factory=dict)
    unknown_len: list[LenNode] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    source: SourceRef | None = None


@dataclass
class FeedResponse:
    feeds: list[Feed] = field(default_factory=list)
    metadata: list[LenNode] = field(default_factory=list)
    all_fields: dict[int, list[Any]] = field(default_factory=dict)
    unknown_len: list[LenNode] = field(default_factory=list)
    timestamp: int | None = None
    source: SourceRef | None = None


@dataclass
class DumpFrame:
    source: SourceRef
    kind: str
    raw: bytes
    content_type: str | None = None
    status: int | None = None


@dataclass
class DiagnosticReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)