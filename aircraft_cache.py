from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from protobuf_export import serialize_message


class AircraftCache:
    """Bounded in-memory cache of the latest positions received from FR24."""

    def __init__(self, max_points: int = 120, max_age: int = 120):
        self.max_points = max_points
        self.max_age = max_age
        self._aircraft: dict[str, dict] = {}
        self._source_stats: list[dict[str, int]] = []
        self._feed_server_time_ms: int | None = None
        self._feed_response_protobuf: list[dict] = []
        self._source_name: str | None = None
        self._lock = threading.RLock()

    def update(self, feeds, source_stats=None, server_time_ms=None, response_protobuf=None, source_name=None) -> None:
        now = time.time()
        with self._lock:
            if source_stats is not None:
                self._source_stats = [dict(item) for item in source_stats]
            if server_time_ms is not None:
                self._feed_server_time_ms = int(server_time_ms)
            if response_protobuf is not None:
                self._feed_response_protobuf = list(response_protobuf)
            if source_name is not None:
                self._source_name = str(source_name)
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
                        "data_source": self._source_name,
                        "callsign": None,
                        "flight_number": None,
                        "registration": None,
                        "origin": None,
                        "destination": None,
                        "diverted_to": None,
                        "aircraft_type": None,
                        "squawk": None,
                        "vertical_speed_fpm": None,
                        "aircraft_age": None,
                        "country_of_reg": None,
                        "icao_address": None,
                        "icao_hex": None,
                        "logo_id": None,
                        "airspace": None,
                        "airspace_id": None,
                        "operated_by_id": None,
                        "squawk_availability": None,
                        "vspeed_availability": None,
                        "airspace_availability": None,
                        "schedule": {},
                        "ems_info": {},
                        "ems_availability": {},
                        "track": None,
                        "icon": None,
                        "status": None,
                        "on_ground": None,
                        "source": None,
                        "timestamp_s": None,
                        "timestamp_ms": None,
                        "points": OrderedDict(),
                        "last_seen": timestamp,
                    },
                )

                raw_message = serialize_message(getattr(feed, "all_fields", {}))
                if raw_message["field_count"]:
                    message_kind = "selected_feed" if getattr(feed, "is_selected", False) else "feed"
                    item.setdefault("protobuf_messages", {})[message_kind] = {
                        "captured_at_ms": int(timestamp * 1000),
                        "message": raw_message,
                    }

                if self._source_name is not None:
                    item["data_source"] = self._source_name

                timestamp_s = getattr(feed, "field_9", None)
                if timestamp_s is not None:
                    item["timestamp_s"] = int(timestamp_s)
                item["timestamp_ms"] = stamp

                callsign = getattr(feed, "field_11", None)
                if callsign:
                    item["callsign"] = str(callsign)

                for name in (
                    "flight_number", "registration", "origin", "destination",
                    "diverted_to", "aircraft_type", "squawk", "vertical_speed_fpm",
                    "aircraft_age", "country_of_reg", "icao_address", "icao_hex",
                    "logo_id", "airspace", "airspace_id", "operated_by_id",
                    "squawk_availability", "vspeed_availability",
                    "airspace_availability",
                ):
                    value = getattr(feed, name, None)
                    if value is not None:
                        item[name] = value

                for name in ("schedule", "ems_info", "ems_availability"):
                    value = getattr(feed, name, None)
                    if value:
                        item[name] = dict(value)

                for name, field_name in (
                    ("track", "field_4"), ("icon", "field_7"),
                    ("status", "field_8"), ("on_ground", "field_10"),
                    ("source", "field_12"),
                ):
                    value = getattr(feed, field_name, None)
                    if value is not None:
                        item[name] = value

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

    def metadata_snapshot(self) -> dict:
        with self._lock:
            return {
                "source_stats": [dict(item) for item in self._source_stats],
                "feed_server_time_ms": self._feed_server_time_ms,
                "feed_response_protobuf": list(self._feed_response_protobuf),
                "source_name": self._source_name,
            }

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
                        "data_source": item.get("data_source"),
                        "callsign": item["callsign"],
                        "flight_number": item.get("flight_number"),
                        "registration": item.get("registration"),
                        "origin": item.get("origin"),
                        "destination": item.get("destination"),
                        "diverted_to": item.get("diverted_to"),
                        "aircraft_type": item.get("aircraft_type"),
                        "squawk": item.get("squawk"),
                        "vertical_speed_fpm": item.get("vertical_speed_fpm"),
                        "aircraft_age": item.get("aircraft_age"),
                        "country_of_reg": item.get("country_of_reg"),
                        "icao_address": item.get("icao_address"),
                        "icao_hex": item.get("icao_hex"),
                        "logo_id": item.get("logo_id"),
                        "airspace": item.get("airspace"),
                        "airspace_id": item.get("airspace_id"),
                        "operated_by_id": item.get("operated_by_id"),
                        "squawk_availability": item.get("squawk_availability"),
                        "vspeed_availability": item.get("vspeed_availability"),
                        "airspace_availability": item.get("airspace_availability"),
                        "schedule": item.get("schedule", {}),
                        "ems_info": item.get("ems_info", {}),
                        "ems_availability": item.get("ems_availability", {}),
                        "track": item.get("track"),
                        "icon": item.get("icon"),
                        "status": item.get("status"),
                        "on_ground": item.get("on_ground"),
                        "source": item.get("source"),
                        "timestamp_s": item.get("timestamp_s"),
                        "timestamp_ms": item.get("timestamp_ms"),
                        "protobuf_messages": item.get("protobuf_messages", {}),
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
