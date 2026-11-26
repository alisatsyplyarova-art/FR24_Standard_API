
#!/usr/bin/env python3
"""Декодирование FeedResponse FR24."""

from __future__ import annotations

from analysis_context import AnalysisContext
from model import (
    Feed,
    FeedResponse,
    PositionHistory,
    PositionSample,
    SourceRef,
    TrackPoint,
)
from len_analyzer import analyze_len_field
from protobuf_parser import (
    WT_VARINT,
    WT_LEN,
    collect_fields,
    first_varint,
    first_fixed32,
    int64_decode,
)

# Подтверждено на fr24_analysis.json (90 точных совпадений, ошибка <= 1e-5 град):
#   lat  = Feed.field_2 - sample.field_1 * 1e-5
#   lon  = Feed.field_3 - sample.field_2 * 1e-5
#   time = Feed.field_15 - sample.field_3   (миллисекунды)
# field_1 и field_2 кодируются как int64 (two's complement), не ZigZag.
COORD_SCALE = 1e-5


def _all_fields(data: bytes):
    return collect_fields(data)


def _first_string(fields, number):
    for item in fields.get(number, []):
        if item.wire_type == WT_LEN:
            try:
                return item.raw_value.decode("utf-8").rstrip("\x00")
            except UnicodeDecodeError:
                return None
    return None


def decode_position_sample(
    data: bytes,
    source: SourceRef | None = None,
) -> PositionSample:
    fields = _all_fields(data)

    sample = PositionSample(
        field_1=first_varint(fields, 1),
        field_2=first_varint(fields, 2),
        field_3=first_varint(fields, 3),
        all_fields=fields,
        source=source,
    )

    for number in (1, 2, 3):
        items = fields.get(number, [])
        if not items or items[0].wire_type != WT_VARINT:
            sample.missing.append(f"field_{number}")

    return sample


def build_track(
    feed: Feed,
    source_frame: int | None = None,
) -> list[TrackPoint]:
    """Строит TrackPoint из Feed: история + текущая позиция, по времени.

    Исходные protobuf-значения сохраняются в raw_fields.
    Сэмплы с неполными полями пропускаются (остаются в feed.histories).
    """
    if feed.field_2 is None or feed.field_3 is None:
        return []

    if source_frame is None:
        source_frame = feed.source.http_record_index if feed.source else -1

    base_time = feed.field_15
    points: list[TrackPoint] = []

    for history_index, history in enumerate(feed.histories):
        for sample_index, sample in enumerate(history.samples):
            if sample.missing:
                continue

            d_lat = int64_decode(sample.field_1)
            d_lon = int64_decode(sample.field_2)

            timestamp = (
                base_time - sample.field_3 if base_time is not None else None
            )

            points.append(
                TrackPoint(
                    latitude=feed.field_2 - d_lat * COORD_SCALE,
                    longitude=feed.field_3 - d_lon * COORD_SCALE,
                    timestamp=timestamp,
                    source_frame=source_frame,
                    raw_fields={
                        "kind": "history",
                        "history_index": history_index,
                        "sample_index": sample_index,
                        "field_1": sample.field_1,
                        "field_2": sample.field_2,
                        "field_3": sample.field_3,
                    },
                )
            )

    points.append(
        TrackPoint(
            latitude=feed.field_2,
            longitude=feed.field_3,
            timestamp=base_time,
            source_frame=source_frame,
            raw_fields={"kind": "current"},
        )
    )

    points.sort(
        key=lambda p: (p.timestamp is None, p.timestamp or 0)
    )
    return points


def merge_tracks(feeds: list[Feed]) -> dict[int, list[TrackPoint]]:
    """Объединяет траектории по ID самолёта.

    Дубли Feed (одинаковые ID и field_15) отбрасываются.
    Точки с одним временем объединяются (остаётся первая).
    """
    seen: set[tuple[int | None, int | None]] = set()
    result: dict[int, dict[int, TrackPoint]] = {}

    for feed in feeds:
        if feed.field_1 is None:
            continue

        key = (feed.field_1, feed.field_15)
        if key in seen:
            continue
        seen.add(key)

        by_time = result.setdefault(feed.field_1, {})
        for point in feed.track:
            if point.timestamp is None:
                continue
            by_time.setdefault(point.timestamp, point)

    return {
        aircraft_id: [points[t] for t in sorted(points)]
        for aircraft_id, points in result.items()
    }


def decode_position_history(
    data: bytes,
    source: SourceRef,
    context: AnalysisContext,
) -> PositionHistory:
    fields = _all_fields(data)

    history = PositionHistory(
        all_fields=fields,
        source=source,
    )

    for item in fields.get(1, []):
        if item.wire_type != WT_LEN:
            continue

        history.samples.append(
            decode_position_sample(item.raw_value, source)
        )

    for number, items in fields.items():
        if number == 1:
            continue

        for index, item in enumerate(items):
            if item.wire_type == WT_LEN:
                history.unknown_len.append(
                    analyze_len_field(
                        number,
                        index,
                        item.raw_value,
                        context,
                        depth=1,
                    )
                )

    return history


def _nested_fields(fields, number):
    """Returns parsed fields from the first length-delimited child message."""
    for item in fields.get(number, []):
        if item.wire_type == WT_LEN:
            try:
                return _all_fields(item.raw_value)
            except (ValueError, TypeError):
                return {}
    return {}


def _nested_string(fields, number):
    return _first_string(fields, number)


def _decode_extra_flight_info(data: bytes) -> dict:
    extra = _all_fields(data)
    route = _nested_fields(extra, 3)
    schedule = _nested_fields(extra, 9)
    ems = _nested_fields(extra, 12)

    icao_address = first_varint(extra, 14)
    icao_hex = (
        f"{icao_address:06X}"
        if icao_address is not None and 0 <= icao_address <= 0xFFFFFF
        else None
    )

    return {
        "flight_number": _nested_string(extra, 1),
        "registration": _nested_string(extra, 2),
        "origin": _nested_string(route, 1),
        "destination": _nested_string(route, 2),
        "diverted_to": _nested_string(route, 3),
        "aircraft_type": _nested_string(extra, 4),
        "squawk": int64_decode(first_varint(extra, 5)) if first_varint(extra, 5) is not None else None,
        "vertical_speed_fpm": int64_decode(first_varint(extra, 6)) if first_varint(extra, 6) is not None else None,
        "aircraft_age": _nested_string(extra, 7),
        "country_of_reg": first_varint(extra, 8),
        "schedule": {
            "std": first_varint(schedule, 1),
            "etd": first_varint(schedule, 2),
            "atd": first_varint(schedule, 3),
            "sta": first_varint(schedule, 4),
            "eta": first_varint(schedule, 5),
            "ata": first_varint(schedule, 6),
            "progress_pct": first_varint(schedule, 7),
        },
        "logo_id": first_varint(extra, 10),
        "airspace": first_varint(extra, 11),
        "ems_info": {
            name: first_varint(ems, number)
            for number, name in (
                (1, "qnh"), (2, "amcp"), (3, "afms"), (4, "oat"),
                (5, "ias"), (6, "tas"), (7, "mach"), (8, "agps"),
                (9, "agpsdiff"), (10, "apflags"), (11, "wind_dir"),
                (12, "wind_speed"), (13, "rs"),
            )
            if first_varint(ems, number) is not None
        },
        "icao_address": icao_address,
        "icao_hex": icao_hex,
        "operated_by_id": first_varint(extra, 15),
        "squawk_availability": bool(first_varint(extra, 16)) if first_varint(extra, 16) is not None else None,
        "vspeed_availability": bool(first_varint(extra, 17)) if first_varint(extra, 17) is not None else None,
        "airspace_availability": bool(first_varint(extra, 18)) if first_varint(extra, 18) is not None else None,
        "airspace_id": _nested_string(extra, 19),
    }


def decode_feed(
    data: bytes,
    source: SourceRef,
    context: AnalysisContext,
) -> Feed:
    fields = _all_fields(data)
    extra_data = next(
        (item.raw_value for item in fields.get(13, []) if item.wire_type == WT_LEN),
        None,
    )
    extra = _decode_extra_flight_info(extra_data) if extra_data is not None else {}

    feed = Feed(
        field_1=first_varint(fields, 1),
        field_2=first_fixed32(fields, 2),
        field_3=first_fixed32(fields, 3),
        field_4=first_varint(fields, 4),
        field_5=first_varint(fields, 5),
        field_6=first_varint(fields, 6),
        field_7=first_varint(fields, 7),
        field_8=first_varint(fields, 8),
        field_9=first_varint(fields, 9),
        field_10=bool(first_varint(fields, 10)) if first_varint(fields, 10) is not None else None,
        field_11=_first_string(fields, 11),
        field_12=first_varint(fields, 12),
        field_15=first_varint(fields, 15),
        all_fields=fields,
        source=source,
        **extra,
    )

    for number in (1, 2, 3, 15):
        if not fields.get(number):
            feed.missing.append(f"field_{number}")

    for index, item in enumerate(fields.get(14, [])):
        if item.wire_type != WT_LEN:
            continue

        feed.histories.append(
            decode_position_history(
                item.raw_value,
                source,
                context,
            )
        )

    feed.track = build_track(feed)

    for number, items in fields.items():
        if number in (11, 13, 14):
            continue

        for index, item in enumerate(items):
            if item.wire_type == WT_LEN:
                feed.unknown_len.append(
                    analyze_len_field(
                        number,
                        index,
                        item.raw_value,
                        context,
                        depth=0,
                    )
                )

    return feed


def decode_feed_response(
    data: bytes,
    source: SourceRef,
    context: AnalysisContext,
) -> FeedResponse:
    fields = _all_fields(data)

    response = FeedResponse(
        all_fields=fields,
        timestamp=first_varint(fields, 4),
        source=source,
    )

    for item in fields.get(1, []):
        if item.wire_type != WT_LEN:
            continue

        response.feeds.append(
            decode_feed(item.raw_value, source, context)
        )

    for index, item in enumerate(fields.get(2, [])):
        if item.wire_type == WT_LEN:
            response.metadata.append(
                analyze_len_field(
                    2,
                    index,
                    item.raw_value,
                    context,
                    depth=0,
                )
            )

    for number, items in fields.items():
        if number in (1, 2):
            continue

        for index, item in enumerate(items):
            if item.wire_type == WT_LEN:
                response.unknown_len.append(
                    analyze_len_field(
                        number,
                        index,
                        item.raw_value,
                        context,
                        depth=0,
                    )
                )

    return response
