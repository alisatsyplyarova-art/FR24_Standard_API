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
    field_4: int | None = None
    field_5: int | None = None
    field_6: int | None = None
    field_7: int | None = None
    field_8: int | None = None
    field_10: bool | None = None
    field_9: int | None = None
    field_11: str | None = None
    field_12: int | None = None
    field_15: int | None = None

    flight_number: str | None = None
    airline_icao: str | None = None
    airline_iata: str | None = None
    airline_name: str | None = None
    airline_short_name: str | None = None
    origin_name: str | None = None
    origin_icao: str | None = None
    origin_country: str | None = None
    origin_country_code: str | None = None
    destination_name: str | None = None
    destination_icao: str | None = None
    destination_country: str | None = None
    destination_country_code: str | None = None
    aircraft_model: str | None = None
    status_text: str | None = None
    registration: str | None = None
    origin: str | None = None
    destination: str | None = None
    diverted_to: str | None = None
    aircraft_type: str | None = None
    squawk: int | None = None
    vertical_speed_fpm: int | None = None
    aircraft_age: str | None = None
    country_of_reg: int | None = None
    logo_id: int | None = None
    airspace: int | None = None
    airspace_id: str | None = None
    icao_address: int | None = None
    icao_hex: str | None = None
    operated_by_id: int | None = None
    squawk_availability: bool | None = None
    vspeed_availability: bool | None = None
    airspace_availability: bool | None = None
    schedule: dict[str, int | None] = field(default_factory=dict)
    ems_info: dict[str, int | None] = field(default_factory=dict)
    ems_availability: dict[str, bool] = field(default_factory=dict)

    histories: list[PositionHistory] = field(default_factory=list)
    track: list[TrackPoint] = field(default_factory=list)
    all_fields: dict[int, list[Any]] = field(default_factory=dict)
    unknown_len: list[LenNode] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    source: SourceRef | None = None
    is_selected: bool = False


@dataclass
class FeedResponse:
    feeds: list[Feed] = field(default_factory=list)
    selected_feeds: list[Feed] = field(default_factory=list)
    stats: list[dict[str, int]] = field(default_factory=list)
    server_time_ms: int | None = None
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