from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class AircraftCache:
    """Bounded in-memory cache of the latest positions received from FR24."""

    def __init__(self, max_points: int = 120, max_age: int = 120):
        self.max_points = max_points
        self.max_age = max_age
        self._aircraft: dict[str, dict] = {}
        self._lock = threading.RLock()

    def update(self, feeds) -> None:
        now = time.time()
        with self._lock:
            for feed in feeds:
                aircraft_id = getattr(feed, "field_1", None)
                latitude = getattr(feed, "field_2", None)
                longitude = getattr(feed, "field_3", None)
                stamp = getattr(feed, "field_15", None)

                if aircraft_id is None or latitude is None or longitude is None or stamp is None:
                    continue

                try:
                    latitude = float(latitude)
                    longitude = float(longitude)
                    stamp = int(stamp)
                except (TypeError, ValueError, OverflowError):
                    continue

                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    continue

                # FR24 Feed timestamps in this project are Unix milliseconds.
                timestamp = stamp / 1000 if stamp > 100_000_000_000 else float(stamp)
                if timestamp > now + 300 or now - timestamp > self.max_age:
                    continue

                key = str(aircraft_id)
                item = self._aircraft.setdefault(
                    key,
                    {
                        "id": key,
                        "callsign": None,
                        "points": OrderedDict(),
                        "last_seen": timestamp,
                    },
                )

                callsign = getattr(feed, "field_11", None)
                if callsign:
                    item["callsign"] = str(callsign)

                altitude_ft = getattr(feed, "field_5", None)
                if altitude_ft is not None:
                    try:
                        item["altitude_ft"] = int(altitude_ft)
                    except (TypeError, ValueError, OverflowError):
                        pass

                speed_kt = getattr(feed, "field_6", None)
                if speed_kt is not None:
                    try:
                        item["speed_kt"] = int(speed_kt)
                    except (TypeError, ValueError, OverflowError):
                        pass

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
                        "altitude_ft": item.get("altitude_ft"),
                        "speed_kt": item.get("speed_kt"),
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

    def log_message(self, fmt, *args):
        # Keep the collector console free of routine HTTP access messages.
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
