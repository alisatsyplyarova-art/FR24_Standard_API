from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


EARTH_KM = 6371.0088


@dataclass(frozen=True)
class RadarArea:
    latitude: float
    longitude: float
    radius_km: float

    @property
    def radius_nm(self) -> float:
        return self.radius_km / 1.852


def _distance_km(a: RadarArea, b: RadarArea) -> float:
    p1, p2 = math.radians(a.latitude), math.radians(b.latitude)
    dp = p2 - p1
    dl = math.radians((b.longitude - a.longitude + 180.0) % 360.0 - 180.0)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


def _destination(start: RadarArea, bearing: float, distance_km: float) -> tuple[float, float]:
    angular = distance_km / EARTH_KM
    lat1 = math.radians(start.latitude)
    lon1 = math.radians(start.longitude)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    lon = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return math.degrees(lat2), lon


def _merge_pair(a: RadarArea, b: RadarArea) -> RadarArea:
    distance = _distance_km(a, b)
    if a.radius_km >= distance + b.radius_km:
        return a
    if b.radius_km >= distance + a.radius_km:
        return b
    if distance < 1e-6:
        return RadarArea(a.latitude, a.longitude, max(a.radius_km, b.radius_km))

    new_radius = (distance + a.radius_km + b.radius_km) / 2.0
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlon = math.radians((b.longitude - a.longitude + 180.0) % 360.0 - 180.0)
    bearing = math.atan2(
        math.sin(dlon) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon),
    )
    shift = max(0.0, new_radius - a.radius_km)
    lat, lon = _destination(a, bearing, shift)
    return RadarArea(lat, lon, new_radius)


def merge_overlapping_areas(areas: list[RadarArea]) -> list[RadarArea]:
    """Merge intersecting radar circles into enclosing circles; keep distant areas separate."""
    merged = list(areas)
    changed = True
    while changed:
        changed = False
        result: list[RadarArea] = []
        while merged:
            current = merged.pop(0)
            index = 0
            while index < len(merged):
                other = merged[index]
                if _distance_km(current, other) <= current.radius_km + other.radius_km:
                    current = _merge_pair(current, other)
                    merged.pop(index)
                    changed = True
                    index = 0
                else:
                    index += 1
            result.append(current)
        merged = result
    return merged


class AreaRegistry:
    """Collects ESP32 radar requests in a short window and keeps recently active areas."""

    def __init__(self, batch_window_seconds: float = 5.0, active_ttl_seconds: float = 35.0):
        self.batch_window_seconds = batch_window_seconds
        self.active_ttl_seconds = active_ttl_seconds
        self._areas: dict[tuple[float, float, float], tuple[RadarArea, float]] = {}
        self._condition = threading.Condition(threading.RLock())
        self._pending = False
        self._last_batch_at = 0.0
        self.requests_total = 0
        self.batches_total = 0

    def register(self, latitude: float, longitude: float, radius_nm: float) -> None:
        area = RadarArea(float(latitude), float(longitude), float(radius_nm) * 1.852)
        key = (round(area.latitude, 4), round(area.longitude, 4), round(area.radius_km, 2))
        now = time.monotonic()
        with self._condition:
            self._areas[key] = (area, now)
            self._pending = True
            self.requests_total += 1
            self._condition.notify_all()

    def _active_locked(self, now: float) -> list[RadarArea]:
        expired = [key for key, (_, stamp) in self._areas.items()
                   if now - stamp > self.active_ttl_seconds]
        for key in expired:
            del self._areas[key]
        return [area for area, _ in self._areas.values()]

    def wait_for_batch(self, timeout: float | None = None) -> list[RadarArea]:
        """Wait for the first ESP request, then collect more requests for the batch window."""
        with self._condition:
            if not self._pending:
                self._condition.wait(timeout=timeout)
            if self._pending:
                deadline = time.monotonic() + self.batch_window_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(timeout=remaining)
                    # Do not restart the window: it is a fixed 5-second collection window.
                self._pending = False
                self.batches_total += 1
                self._last_batch_at = time.time()
            return merge_overlapping_areas(self._active_locked(time.monotonic()))

    def snapshot(self) -> list[RadarArea]:
        with self._condition:
            return merge_overlapping_areas(self._active_locked(time.monotonic()))

    def stats(self) -> dict:
        with self._condition:
            active = self._active_locked(time.monotonic())
            return {
                "registered_areas": len(active),
                "merged_areas": len(merge_overlapping_areas(active)),
                "requests_total": self.requests_total,
                "batches_total": self.batches_total,
                "batch_window_seconds": self.batch_window_seconds,
                "active_ttl_seconds": self.active_ttl_seconds,
                "last_batch_at": self._last_batch_at or None,
            }


AREAS = AreaRegistry()
