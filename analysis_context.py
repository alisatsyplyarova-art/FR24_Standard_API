#!/usr/bin/env python3
"""Общий контекст анализа и ограничения рекурсии."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AnalysisContext:
    max_depth: int = 8
    max_nodes: int = 10000
    max_message_size: int = 1024 * 1024

    nodes_seen: int = 0
    bytes_seen: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def enter(self, depth: int, size: int) -> tuple[bool, str | None]:
        """Регистрирует новый узел и проверяет ограничения."""
        if depth > self.max_depth:
            return False, "max_depth exceeded"

        if self.nodes_seen >= self.max_nodes:
            return False, "max_nodes exceeded"

        if size > self.max_message_size:
            return False, "max_message_size exceeded"

        self.nodes_seen += 1
        self.bytes_seen += size
        return True, None

    def add_error(self, message: str) -> None:
        self.errors.append(str(message))

    def add_warning(self, message: str) -> None:
        self.warnings.append(str(message))

    def reset(self) -> None:
        self.nodes_seen = 0
        self.bytes_seen = 0
        self.errors.clear()
        self.warnings.clear()