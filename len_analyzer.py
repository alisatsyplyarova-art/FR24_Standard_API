#!/usr/bin/env python3
"""Рекурсивный анализ protobuf LEN-полей."""

from __future__ import annotations

from analysis_context import AnalysisContext
from model import LenNode
from protobuf_parser import (
    WT_LEN,
    STATUS_DECODED,
    STATUS_EMPTY,
    STATUS_INVALID,
    STATUS_OPAQUE,
    iter_fields,
)


def analyze_len_field(
    field_number: int,
    field_index: int,
    content: bytes,
    context: AnalysisContext,
    depth: int = 0,
) -> LenNode:

    node = LenNode(
        field_number=field_number,
        field_index=field_index,
        original_bytes=content,
        status=STATUS_OPAQUE,
        depth=depth,
    )

    allowed, reason = context.enter(depth, len(content))

    if not allowed:
        node.status = STATUS_OPAQUE
        node.error = reason
        return node

    if not content:
        node.status = STATUS_EMPTY
        return node

    try:
        fields = list(iter_fields(content))
    except (ValueError, TypeError) as exc:
        node.status = STATUS_INVALID
        node.error = str(exc)
        context.add_warning(
            f"LEN field {field_number}[{field_index}]: {exc}"
        )
        return node

    node.fields = fields
    node.status = STATUS_DECODED

    for number, field in enumerate(fields):
        if field.wire_type != WT_LEN:
            continue

        child = analyze_len_field(
            field_number=field.number,
            field_index=number,
            content=field.raw_value,
            context=context,
            depth=depth + 1,
        )

        node.nested.append(child)

    return node