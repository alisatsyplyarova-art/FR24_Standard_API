from __future__ import annotations

import json
import math
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from aircraft_cache import CACHE


_ROUTE = re.compile(r"^/v2/lat/(-?\d+(?:\.\d+)?)/lon/(-?\d+(?:\.\d+)?)/dist/(\d+(?:\.\d+)?)$")
_EARTH_RADIUS_NM = 3440.065

# Последняя область, запрошенная ESP32. До первого запроса используется radar_config.json.
_ACTIVE_AREA_LOCK = threading.RLock()
_ACTIVE_AREA: dict | None = None


def set_active_area(latitude: float, longitude: float, radius_nm: float) -> None:
    global _ACTIVE_AREA
    with _ACTIVE_AREA_LOCK:
        _ACTIVE_AREA = {
            "latitude": latitude,
            "longitude": longitude,
            "radius_km": radius_nm * 1.852,
            "radius_nm": radius_nm,
        }


def get_active_area(default: dict | None = None) -> dict | None:
    with _ACTIVE_AREA_LOCK:
        if _ACTIVE_AREA is not None:
            return dict(_ACTIVE_AREA)
    return dict(default) if default is not None else None


def _distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


class _Handler(BaseHTTPRequestHandler):
    server_version = "FR24StandardAPI/1.0"

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
            area = get_active_area()
            self._send_json(200, {
                "status": "ok",
                "aircraft": len(aircraft),
                "active_area": area,
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
        # Прошивка 1.1.127 ограничивает запрос радиусом 500 NM.
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 < radius_nm <= 500):
            self._send_json(400, {"msg": "Invalid latitude, longitude or distance (maximum 500 NM)"})
            return

        # Область запроса ESP32 становится областью следующего опроса LiveFeed.
        # Так сервер не ограничивается координатами из radar_config.json.
        set_active_area(lat, lon, radius_nm)

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
            if item.get("altitude_ft") is not None:
                row["altitude_ft"] = item["altitude_ft"]
            if item.get("speed_kt") is not None:
                row["speed_kt"] = item["speed_kt"]
            if item.get("heading") is not None:
                row["track"] = round(item["heading"], 1)
            selected.append(row)

        selected.sort(key=lambda row: row["_distance_nm"])
        for row in selected:
            row.pop("_distance_nm", None)

        now_ms = int(now * 1000)
        self._send_json(200, {
            "ac": selected,
            "msg": "No error",
            "now": now_ms,
            "total": len(selected),
            "ctime": now_ms,
            "ptime": 0,
        })

    def log_message(self, fmt: str, *args) -> None:
        return


def start_api_server(host: str = "0.0.0.0", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    threading.Thread(target=server.serve_forever, name="FR24StandardAPI", daemon=True).start()
    return server

