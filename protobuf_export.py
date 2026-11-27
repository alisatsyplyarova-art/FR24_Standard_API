"""JSON-safe export of protobuf messages without losing original wire data."""

from __future__ import annotations

import base64
from typing import Any

from protobuf_parser import WT_32BIT, WT_64BIT, WT_LEN, WT_VARINT


_WIRE_NAMES = {
    WT_VARINT: "varint",
    WT_64BIT: "fixed64",
    WT_LEN: "length_delimited",
    WT_32BIT: "fixed32",
}


def serialize_message(fields: dict[int, list[Any]]) -> dict:
    """Serialize every protobuf field, preserving exact encoded and value bytes.

    The exporter deliberately does not guess the semantic type of unknown
    fields. For every occurrence it exports the field number, wire type,
    offset, raw value and complete raw field encoding.
    """
    entries = []
    for number, occurrences in fields.items():
        for field in occurrences:
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
            elif field.wire_type in (WT_32BIT, WT_64BIT):
                # Keep the exact bytes; their semantic interpretation depends
                # on the schema and must not be guessed here.
                entry["value_bytes"] = len(raw_value)
            entries.append(entry)

    entries.sort(key=lambda item: item["offset"])
    return {
        "field_count": len(entries),
        "fields": entries,
    }
