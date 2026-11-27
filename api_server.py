from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from aircraft_cache import CACHE
from area_manager import AREAS


_ROUTE = re.compile(r"^/v2/lat/(-?\d+(?:\.\d+)?)/lon/(-?\d+(?:\.\d+)?)/dist/(\d+(?:\.\d+)?)$")
_EARTH_RADIUS_NM = 3440.065
_RESPONSE_CACHE_TTL = 5.0
_RESPONSE_CACHE_MAX = 512
_RESPONSE_CACHE: OrderedDict[tuple[float, float, float], tuple[float, dict]] = OrderedDict()
_RESPONSE_CACHE_LOCK = threading.RLock()


def _distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def _cached_response(key: tuple[float, float, float], now: float) -> dict | None:
    with _RESPONSE_CACHE_LOCK:
        item = _RESPONSE_CACHE.get(key)
        if item is None:
            return None
        created, payload = item
        if now - created > _RESPONSE_CACHE_TTL:
            del _RESPONSE_CACHE[key]
            return None
        _RESPONSE_CACHE.move_to_end(key)
        return payload


def _store_response(key: tuple[float, float, float], now: float, payload: dict) -> None:
    with _RESPONSE_CACHE_LOCK:
        _RESPONSE_CACHE[key] = (now, payload)
        _RESPONSE_CACHE.move_to_end(key)
        while len(_RESPONSE_CACHE) > _RESPONSE_CACHE_MAX:
            _RESPONSE_CACHE.popitem(last=False)


class _Handler(BaseHTTPRequestHandler):
    server_version = "FR24StandardAPI/2.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        now = time.time()

        if path == "/health":
            aircraft = CACHE.snapshot()
            self._send_json(200, {
                "status": "ok",
                "aircraft": len(aircraft),
                "areas": AREAS.stats(),
                "now": int(now * 1000),
            })
            return

        if path == "/aircraft":
            aircraft = CACHE.snapshot()
            self._send_json(200, {"aircraft": aircraft, "count": len(aircraft), "timestamp": now})
            return

        match = _ROUTE.fullmatch(path)
        if not match:
            self._send_json(404, {"msg": "Not found"})
            return

        lat, lon, radius_nm = map(float, match.groups())
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 < radius_nm <= 500):
            self._send_json(400, {"msg": "Invalid latitude, longitude or distance (maximum 500 NM)"})
            return

        AREAS.register(lat, lon, radius_nm)
        key = (round(lat, 4), round(lon, 4), round(radius_nm, 2))
        cached = _cached_response(key, now)
        if cached is not None:
            self._send_json(200, cached)
            return

        selected = []
        for item in CACHE.snapshot():
            current = item["current"]
            distance = _distance_nm(lat, lon, current["latitude"], current["longitude"])
            if distance > radius_nm:
                continue
            seen_pos = max(0.0, now - current["timestamp"] / 1000.0)
            row = {
                "fr24_id": item["id"],
                "lat": current["latitude"],
                "lon": current["longitude"],
                "seen": max(0.0, now - item["last_seen"]),
                "seen_pos": seen_pos,
                "_distance_nm": distance,
            }
            if item.get("callsign"):
                row["flight"] = item["callsign"]

            # Forward only documented FR24 metadata. Preserve valid false/zero
            # values; omit fields that were not present in the upstream feed.
            for name in (
                "on_ground",
                "altitude_ft",
                "speed_kt",
                "aircraft_type",
                "registration",
                "flight_number",
                "origin",
                "destination",
                "squawk",
                "vertical_speed_fpm",
                "aircraft_age",
                "country_of_reg",
                "icao_address",
                "status",
                "icon",
                "source",
            ):
                value = item.get(name)
                if value is not None:
                    row[name] = value

            if item.get("icao_hex"):
                row["hex"] = item["icao_hex"]
            if item.get("track") is not None:
                row["track"] = item["track"]
            elif item.get("heading") is not None:
                row["track"] = round(item["heading"], 1)

            selected.append(row)

        selected.sort(key=lambda row: row["_distance_nm"])
        for row in selected:
            row.pop("_distance_nm", None)

        now_ms = int(now * 1000)
        payload = {
            "ac": selected,
            "msg": "No error",
            "now": now_ms,
            "total": len(selected),
            "ctime": now_ms,
            "ptime": 0,
        }
        _store_response(key, now, payload)
        self._send_json(200, payload)

    def log_message(self, fmt: str, *args) -> None:
        return


def start_api_server(host: str = "0.0.0.0", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    threading.Thread(target=server.serve_forever, name="FR24StandardAPI", daemon=True).start()
    return server
