from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AreaKey:
    latitude: float
    longitude: float
    radius_km: float


class AreaScheduler:
    """Fair round-robin selector that caps upstream areas handled per cycle."""

    def __init__(self) -> None:
        self._cursor = 0

    @staticmethod
    def _key(area) -> tuple[float, float, float]:
        return (
            round(float(area.latitude), 4),
            round(float(area.longitude), 4),
            round(float(area.radius_km), 2),
        )

    def select(self, areas: list, limit: int) -> list:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        unique = []
        seen = set()
        for area in areas:
            key = self._key(area)
            if key not in seen:
                unique.append(area)
                seen.add(key)
        if not unique:
            self._cursor = 0
            return []
        start = self._cursor % len(unique)
        count = min(limit, len(unique))
        selected = [unique[(start + offset) % len(unique)] for offset in range(count)]
        self._cursor = (start + count) % len(unique)
        return selected
