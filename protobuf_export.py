"""JSON-safe export of protobuf messages without losing original wire data."""

from __future__ import annotations

import base64
from typing import Any

from protobuf_parser import (
    WT_32BIT,
    WT_64BIT,
    WT_LEN,
    WT_VARINT,
    collect_fields,
)


_WIRE_NAMES = {
    WT_VARINT: "varint",
    WT_64BIT: "fixed64",
    WT_LEN: "length_delimited",
    WT_32BIT: "fixed32",
}
_MAX_NESTED_DEPTH = 8
_MAX_TOTAL_FIELDS = 10000


def serialize_message(
    fields: dict[int, list[Any]],
    *,
    _depth: int = 0,
    _budget: list[int] | None = None,
) -> dict:
    """Export every field and preserve exact bytes at every parsed level.

    LEN payloads are also tested as possible nested protobuf messages. Such
    children are explicitly labelled as candidates: wire-valid bytes alone do
    not establish their semantic schema. The original LEN bytes are always
    retained regardless of whether nested parsing succeeds.
    """
    if _budget is None:
        _budget = [0]

    entries = []
    for occurrences in fields.values():
        for field in occurrences:
            _budget[0] += 1
            raw_value = bytes(field.raw_value)
            raw_field = bytes(field.raw_bytes)
            entry = {
                "number": int(field.number),
                "wire_type": int(field.wire_type),
                "wire_type_name": _WIRE_NAMES.get(field.wire_type, "unknown"),
                "offset": int(field.offset),
                "raw_value_base64": base64.b64encode(raw_value).decode("ascii"),
                "raw_value_hex": raw_value.hex(),
                "raw_field_base64": base64.b64encode(raw_field).decode("ascii"),
                "raw_field_hex": raw_field.hex(),
            }

            if field.wire_type == WT_VARINT:
                entry["value_uint64"] = int(field.value)
            elif field.wire_type == WT_LEN:
                entry["length"] = len(raw_value)
                if _depth >= _MAX_NESTED_DEPTH:
                    entry["nested_parse_status"] = "depth_limit"
                elif _budget[0] >= _MAX_TOTAL_FIELDS:
                    entry["nested_parse_status"] = "field_limit"
                else:
                    try:
                        nested_fields = collect_fields(raw_value)
                    except (TypeError, ValueError):
                        entry["nested_parse_status"] = "not_valid_protobuf"
                    else:
                        if nested_fields:
                            entry["nested_parse_status"] = "protobuf_candidate"
                            entry["nested_candidate"] = serialize_message(
                                nested_fields,
                                _depth=_depth + 1,
                                _budget=_budget,
                            )
                        else:
                            entry["nested_parse_status"] = "empty"
            elif field.wire_type in (WT_32BIT, WT_64BIT):
                # Keep exact bytes; semantic interpretation depends on schema.
                entry["value_bytes"] = len(raw_value)

            entries.append(entry)

    entries.sort(key=lambda item: item["offset"])
    return {
        "field_count": len(entries),
        "fields": entries,
    }
