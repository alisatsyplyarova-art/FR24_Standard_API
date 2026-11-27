from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _number(value):
    if value is None or value == "N/A":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


class AircraftCache:
    """Bounded in-memory cache for live aircraft returned by FlightRadarAPI."""

    def __init__(self, max_points: int = 120, max_age: int = 120):
        self.max_points = max_points
        self.max_age = max_age
        self._aircraft: dict[str, dict] = {}
        self._lock = threading.RLock()

    def update(self, flights) -> None:
        now = time.time()
        with self._lock:
            for flight in flights:
                # Accept both the previous protobuf Feed model and FlightRadarAPI Flight.
                aircraft_id = getattr(flight, "field_1", None)
                if aircraft_id is None:
                    aircraft_id = getattr(flight, "id", None)

                latitude = _number(getattr(flight, "field_2", None))
                if latitude is None:
                    latitude = _number(getattr(flight, "latitude", None))
                longitude = _number(getattr(flight, "field_3", None))
                if longitude is None:
                    longitude = _number(getattr(flight, "longitude", None))

                stamp = getattr(flight, "field_15", None)
                if stamp is None:
                    stamp = getattr(flight, "time", None)
                stamp_number = _number(stamp)

                if aircraft_id is None or latitude is None or longitude is None or stamp_number is None:
                    continue
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    continue

                # FlightRadarAPI exposes feed time in Unix seconds; the legacy
                # protobuf decoder used milliseconds for large values.
                timestamp = stamp_number / 1000 if stamp_number > 100_000_000_000 else stamp_number
                if timestamp <= 0 or timestamp > now + 300 or now - timestamp > self.max_age:
                    continue

                key = str(aircraft_id)
                item = self._aircraft.setdefault(
                    key,
                    {
                        "id": key,
                        "callsign": None,
                        "altitude": None,
                        "ground_speed": None,
                        "points": OrderedDict(),
                        "last_seen": timestamp,
                    },
                )

                callsign = getattr(flight, "field_11", None) or getattr(flight, "callsign", None)
                if callsign and callsign != "N/A":
                    item["callsign"] = str(callsign)

                altitude = _number(getattr(flight, "altitude", None))
                ground_speed = _number(getattr(flight, "ground_speed", None))
                if altitude is not None:
                    item["altitude"] = altitude
                if ground_speed is not None:
                    item["ground_speed"] = ground_speed

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
            aircraft_id
            for aircraft_id, item in self._aircraft.items()
            if now - item["last_seen"] > self.max_age
        ]
        for aircraft_id in stale_ids:
            del self._aircraft[aircraft_id]

    def snapshot(self) -> list[dict]:
        now = time.time()
        with self._lock:
            self._remove_stale(now)
            result = []

            for item in self._aircraft.values():
                points = list(item["points"].values())
                if not points:
                    continue

                heading = None
                if len(points) >= 2:
                    previous = points[-2]
                    current = points[-1]
                    lat1 = math.radians(previous["latitude"])
                    lat2 = math.radians(current["latitude"])
                    delta_lon = math.radians(
                        current["longitude"] - previous["longitude"]
                    )
                    y = math.sin(delta_lon) * math.cos(lat2)
                    x = (
                        math.cos(lat1) * math.sin(lat2)
                        - math.sin(lat1)
                        * math.cos(lat2)
                        * math.cos(delta_lon)
                    )
                    heading = (math.degrees(math.atan2(y, x)) + 360) % 360

                result.append(
                    {
                        "id": item["id"],
                        "callsign": item["callsign"],
                        "altitude": item["altitude"],
                        "ground_speed": item["ground_speed"],
                        "points": points,
                        "current": points[-1],
                        "heading": heading,
                        "point_count": len(points),
                        "last_seen": item["last_seen"],
                    }
                )

            return result


CACHE = AircraftCache()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] != "/aircraft":
            self.send_error(404, "Not Found")
            return

        aircraft = CACHE.snapshot()
        payload = json.dumps(
            {
                "aircraft": aircraft,
                "count": len(aircraft),
                "timestamp": time.time(),
            },
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args):
        return


def start_api_server(host: str = "127.0.0.1", port: int = 8765):
    """Start the local API in a daemon thread and return its server object."""
    server = ThreadingHTTPServer((host, port), _Handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="FR24LocalAPI",
        daemon=True,
    )
    thread.start()
    return server
