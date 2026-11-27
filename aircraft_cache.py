from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from datetime import date, datetime


def _number(value):
    if value is None or value == "N/A":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _json_value(value, depth=0):
    """Convert FlightRadarAPI values to bounded JSON-safe data."""
    if depth > 5:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        if value == "N/A":
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {
            str(k): _json_value(v, depth + 1)
            for k, v in list(value.items())[:300]
            if not str(k).startswith("_")
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_value(v, depth + 1) for v in list(value)[:300]]
    if hasattr(value, "__dict__"):
        return {
            str(k): _json_value(v, depth + 1)
            for k, v in vars(value).items()
            if not str(k).startswith("_") and not callable(v)
        }
    return str(value)


_FEED_FIELDS = (
    "id", "latitude", "longitude", "altitude", "heading", "ground_speed",
    "vertical_speed", "on_ground", "time", "callsign", "number", "squawk",
    "icao_24bit", "registration", "aircraft_code", "airline_icao",
    "airline_iata", "origin_airport_iata", "destination_airport_iata",
)
_DETAIL_FIELDS = (
    "aircraft_model", "aircraft_age", "aircraft_country_id", "aircraft_images",
    "aircraft_history", "airline_name", "airline_short_name",
    "airline_country_name", "airline_country", "airline_country_code",
    "airline_country_id", "status_text", "status_icon", "time_details", "trail",
)
_AIRPORT_FIELDS = (
    "name", "icao", "latitude", "longitude", "altitude", "country_name",
    "country_code", "terminal", "gate", "baggage", "timezone_name",
    "timezone_abbr", "timezone_abbr_name", "timezone_offset",
    "timezone_offset_hours", "visible", "website",
)
for _prefix in ("origin", "destination"):
    for _field in _AIRPORT_FIELDS:
        _DETAIL_FIELDS += (f"{_prefix}_airport_{_field}",)


class AircraftCache:
    """Bounded cache of live positions and on-demand FR24 flight details."""

    def __init__(self, max_points: int = 120, max_age: int = 120):
        self.max_points = max_points
        self.max_age = max_age
        self._aircraft: dict[str, dict] = {}
        self._lock = threading.RLock()

    def update(self, flights) -> None:
        now = time.time()
        with self._lock:
            for flight in flights:
                aircraft_id = getattr(flight, "id", None)
                latitude = _number(getattr(flight, "latitude", None))
                longitude = _number(getattr(flight, "longitude", None))
                stamp = _number(getattr(flight, "time", None))
                if aircraft_id is None or latitude is None or longitude is None or stamp is None:
                    continue
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    continue

                timestamp = stamp / 1000 if stamp > 100_000_000_000 else stamp
                if timestamp <= 0 or timestamp > now + 300 or now - timestamp > self.max_age:
                    continue

                key = str(aircraft_id)
                item = self._aircraft.setdefault(
                    key,
                    {"id": key, "points": OrderedDict(), "last_seen": timestamp,
                     "details": None, "details_error": None},
                )
                item["_flight"] = flight

                for field in _FEED_FIELDS:
                    value = _json_value(getattr(flight, field, None))
                    if value is not None:
                        item[field] = value

                point = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "timestamp": int(timestamp * 1000),
                }
                item["points"][timestamp] = point
                item["points"] = OrderedDict(sorted(item["points"].items()))
                while len(item["points"]) > self.max_points:
                    item["points"].popitem(last=False)
                item["last_seen"] = max(item["last_seen"], timestamp)

            self._remove_stale(now)

    def _remove_stale(self, now: float) -> None:
        stale_ids = [
            aircraft_id for aircraft_id, item in self._aircraft.items()
            if now - item["last_seen"] > self.max_age
        ]
        for aircraft_id in stale_ids:
            del self._aircraft[aircraft_id]

    def _flight_fields(self, flight) -> dict:
        result = {}
        for field in _FEED_FIELDS + _DETAIL_FIELDS:
            value = _json_value(getattr(flight, field, None))
            if value is not None and value != [] and value != {}:
                result[field] = value

        # Preserve additional public attributes supplied by future SDK versions.
        try:
            for key, value in vars(flight).items():
                if key.startswith("_") or callable(value) or key in result:
                    continue
                converted = _json_value(value)
                if converted is not None:
                    result[key] = converted
        except TypeError:
            pass
        return result

    def get_details(self, aircraft_id: str, details_loader):
        key = str(aircraft_id)
        with self._lock:
            item = self._aircraft.get(key)
            if item is None:
                return None
            if item.get("details") is not None:
                return item["details"]
            flight = item.get("_flight")

        if flight is None:
            return None
        if details_loader is None:
            raise RuntimeError("Flight details provider is not configured")

        raw = details_loader(flight)
        if hasattr(flight, "set_flight_details"):
            flight.set_flight_details(raw)

        details = self._flight_fields(flight)
        details["raw_details"] = _json_value(raw)

        with self._lock:
            current = self._aircraft.get(key)
            if current is None:
                return details
            current["details"] = details
            current["details_error"] = None
        return details

    def snapshot(self) -> list[dict]:
        now = time.time()
        with self._lock:
            self._remove_stale(now)
            result = []
            for item in self._aircraft.values():
                points = list(item["points"].values())
                if not points:
                    continue

                heading = _number(item.get("heading"))
                if heading is None and len(points) >= 2:
                    previous, current = points[-2], points[-1]
                    lat1, lat2 = math.radians(previous["latitude"]), math.radians(current["latitude"])
                    delta_lon = math.radians(current["longitude"] - previous["longitude"])
                    y = math.sin(delta_lon) * math.cos(lat2)
                    x = (math.cos(lat1) * math.sin(lat2)
                         - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon))
                    heading = (math.degrees(math.atan2(y, x)) + 360) % 360

                row = {k: v for k, v in item.items() if not k.startswith("_") and k not in ("points", "details_error")}
                row.update({
                    "id": item["id"],
                    "points": points,
                    "current": points[-1],
                    "heading": heading,
                    "altitude_ft": item.get("altitude"),
                    "speed_kt": item.get("ground_speed"),
                    "point_count": len(points),
                    "last_seen": item["last_seen"],
                })
                result.append(row)
            return result


CACHE = AircraftCache()
