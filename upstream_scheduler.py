from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AreaKey:
    latitude: float
    longitude: float
    radius_km: float


class AreaScheduler:
    """Stable-key round-robin selector with a hard per-cycle area cap."""

    def __init__(self) -> None:
        self._next_key: tuple[float, float, float] | None = None

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
            self._next_key = None
            return []

        keys = [self._key(area) for area in unique]
        try:
            start = keys.index(self._next_key)
        except ValueError:
            start = 0

        count = min(limit, len(unique))
        selected = [unique[(start + offset) % len(unique)] for offset in range(count)]
        self._next_key = keys[(start + count) % len(unique)]
        return selected
