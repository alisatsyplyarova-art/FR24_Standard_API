from __future__ import annotations

import json
import logging
import math
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from aircraft_cache import CACHE
from analysis_context import AnalysisContext
from api_server import start_api_server
from area_manager import AREAS, RadarArea
from feed_decoder import decode_feed_response
from grpc_web import decode_grpc_web_body
from model import SourceRef
from upstream_scheduler import AreaScheduler
from upstream_client import UpstreamClient

BASE_DIR = Path(__file__).resolve().parent
HAR_FILE = BASE_DIR / "www.flightradar24.com.har"
CONFIG_FILE = BASE_DIR / "radar_config.json"
CAPTURE_DIR = BASE_DIR / "captures"
LOG_DIR = BASE_DIR / "logs"

URL = "https://data-feed.flightradar24.com/fr24.feed.api.v1.Feed/LiveFeed"
INTERVAL_SECONDS = 10
BATCH_WINDOW_SECONDS = 5
TIMEOUT_SECONDS = 20
DEFAULT_MAX_AREAS_PER_CYCLE = 20
DEFAULT_UPSTREAM_INTERVAL_SECONDS = 0.25
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
API_HOST = "0.0.0.0"
API_PORT = 8765

ALLOWED_HEADERS = {
    "content-type", "x-grpc-web", "x-user-agent", "fr24-device-id",
    "fr24-platform", "origin", "referer", "user-agent", "accept",
}


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "collector.log", encoding="utf-8"),
        ],
    )


def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        raise FileNotFoundError(f"Config not found: {CONFIG_FILE}")
    with CONFIG_FILE.open("r", encoding="utf-8-sig") as file:
        config = json.load(file)
    lat, lon, radius_km = float(config["latitude"]), float(config["longitude"]), float(config["radius_km"])
    if not all(math.isfinite(v) for v in (lat, lon, radius_km)):
        raise ValueError("Radar settings must be finite numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinates are out of range")
    if not (0 < radius_km <= 20000):
        raise ValueError("Radius must be between 0 and 20000 km")
    settings = {
        "latitude": lat,
        "longitude": lon,
        "radius_km": radius_km,
        "max_areas_per_cycle": int(config.get("max_areas_per_cycle", DEFAULT_MAX_AREAS_PER_CYCLE)),
        "upstream_interval_seconds": float(config.get("upstream_interval_seconds", DEFAULT_UPSTREAM_INTERVAL_SECONDS)),
        "max_retries": int(config.get("max_retries", DEFAULT_MAX_RETRIES)),
        "retry_backoff_seconds": float(config.get("retry_backoff_seconds", DEFAULT_RETRY_BACKOFF_SECONDS)),
        "request_timeout_seconds": float(config.get("request_timeout_seconds", TIMEOUT_SECONDS)),
        "active_area_ttl_seconds": float(config.get("active_area_ttl_seconds", 35.0)),
        "save_captures": bool(config.get("save_captures", False)),
    }
    if not (1 <= settings["max_areas_per_cycle"] <= 500):
        raise ValueError("max_areas_per_cycle must be between 1 and 500")
    if not (0 <= settings["upstream_interval_seconds"] <= 60):
        raise ValueError("upstream_interval_seconds must be between 0 and 60")
    if not (0 <= settings["max_retries"] <= 5):
        raise ValueError("max_retries must be between 0 and 5")
    if not (0.1 <= settings["retry_backoff_seconds"] <= 60):
        raise ValueError("retry_backoff_seconds must be between 0.1 and 60")
    if not (1 <= settings["request_timeout_seconds"] <= 120):
        raise ValueError("request_timeout_seconds must be between 1 and 120")
    if not (10 <= settings["active_area_ttl_seconds"] <= 600):
        raise ValueError("active_area_ttl_seconds must be between 10 and 600")
    return settings


def build_request_body(template: bytes, config: dict | None = None) -> bytes:
    config = config or load_config()
    lat, lon, radius_km = config["latitude"], config["longitude"], config["radius_km"]
    angular = radius_km / 6371.0088
    lat_delta = math.degrees(angular)
    north, south = min(90.0, lat + lat_delta), max(-90.0, lat - lat_delta)
    if abs(lat) + lat_delta >= 90:
        lon_delta = 180.0
    else:
        ratio = math.sin(angular) / math.cos(math.radians(lat))
        lon_delta = math.degrees(math.asin(min(1.0, max(-1.0, ratio))))
    west, east = lon - lon_delta, lon + lon_delta
    if west < -180 or east > 180:
        raise ValueError("Radar area crosses the date line; adjust longitude/radius")

    result = bytearray(template)
    if (len(result) != 70 or result[:7] != bytes((0, 0, 0, 0, 65, 10, 20))
            or [result[i] for i in (7, 12, 17, 22)] != [13, 21, 29, 37]):
        raise ValueError("Unexpected HAR protobuf template; refusing to alter request")
    for offset, value in zip((8, 13, 18, 23), (north, south, west, east)):
        struct.pack_into("<f", result, offset, value)
    return bytes(result)


def load_request_template() -> tuple[bytes, dict[str, str]]:
    if not HAR_FILE.is_file():
        raise FileNotFoundError(f"HAR file not found: {HAR_FILE}")
    with HAR_FILE.open("r", encoding="utf-8-sig") as file:
        har = json.load(file)
    entries = har.get("log", {}).get("entries", [])
    entry = next((item for item in entries
                  if item.get("request", {}).get("url") == URL
                  and item.get("request", {}).get("method") == "POST"
                  and item.get("request", {}).get("postData", {}).get("text")), None)
    if entry is None:
        raise RuntimeError("POST LiveFeed request was not found in HAR")
    request = entry["request"]
    body = request["postData"]["text"].encode("latin1")
    headers = {h["name"]: h["value"] for h in request.get("headers", [])
               if h.get("name", "").lower() in ALLOWED_HEADERS}
    if not body or not headers:
        raise RuntimeError("HAR LiveFeed request is missing its body or allowed headers")
    return body, headers


def decode_response(data: bytes, request_index: int) -> tuple[list, list[str]]:
    frames = decode_grpc_web_body(data)
    feeds, errors = [], []
    for frame_index, frame in enumerate(frames):
        if not frame.is_data:
            continue
        if frame.is_compressed:
            errors.append(f"frame {frame_index}: compressed payload skipped")
            continue
        source = SourceRef(request_index, frame_index, 0)
        try:
            feeds.extend(decode_feed_response(frame.payload, source, AnalysisContext()).feeds)
        except Exception as exc:
            errors.append(f"frame {frame_index}: {type(exc).__name__}: {exc}")
    return feeds, errors


def area_config(area: RadarArea) -> dict:
    return {"latitude": area.latitude, "longitude": area.longitude, "radius_km": area.radius_km}


def main() -> None:
    setup_logging()
    config = load_config()
    template, headers = load_request_template()
    build_request_body(template, config)

    server = start_api_server(API_HOST, API_PORT)
    session = requests.Session()
    scheduler = AreaScheduler()
    AREAS.active_ttl_seconds = config["active_area_ttl_seconds"]
    request_index = 0
    upstream = UpstreamClient(
        session,
        min_interval_seconds=config["upstream_interval_seconds"],
        max_retries=config["max_retries"],
        backoff_seconds=config["retry_backoff_seconds"],
        timeout_seconds=config["request_timeout_seconds"],
    )
    logging.info("FR24 multi-area collector started; API http://%s:%d", API_HOST, API_PORT)
    logging.info(
        "ESP batch window: %d sec; collector interval: %d sec; response cache: 5 sec; "
        "max areas/cycle=%d; upstream gap=%.2fs; retries=%d",
        BATCH_WINDOW_SECONDS, INTERVAL_SECONDS, config["max_areas_per_cycle"],
        config["upstream_interval_seconds"], config["max_retries"],
    )

    try:
        while True:
            cycle_started = time.monotonic()
            areas = AREAS.wait_for_batch(timeout=INTERVAL_SECONDS)
            if not areas:
                areas = [RadarArea(config["latitude"], config["longitude"], config["radius_km"])]

            selected_areas = scheduler.select(areas, config["max_areas_per_cycle"])
            logging.info(
                "Batch ready: %d merged area(s), processing %d this cycle; registry=%s",
                len(areas), len(selected_areas), AREAS.stats(),
            )
            if len(areas) > len(selected_areas):
                logging.warning(
                    "Upstream area limit reached: %d deferred to later cycles",
                    len(areas) - len(selected_areas),
                )
            cycle_feeds = 0
            for area_index, area in enumerate(selected_areas, start=1):
                try:
                    request_index += 1
                    response = upstream.post(
                        URL,
                        data=build_request_body(template, area_config(area)),
                        headers=headers,
                    )
                    logging.info(
                        "FR24 request #%d area %d/%d: HTTP %d, %d bytes; center %.5f, %.5f radius %.1f km",
                        request_index, area_index, len(selected_areas), response.status_code, len(response.content),
                        area.latitude, area.longitude, area.radius_km,
                    )
                    if not response.content:
                        logging.warning("FR24 request #%d returned an empty body", request_index)
                        continue
                    if config["save_captures"]:
                        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                        (CAPTURE_DIR / f"live_{stamp}.bin").write_bytes(response.content)
                    feeds, errors = decode_response(response.content, request_index)
                    CACHE.update(feeds)
                    cycle_feeds += len(feeds)
                    for error in errors[:5]:
                        logging.warning("Decode warning: %s", error)
                except PermissionError:
                    logging.exception("FR24 access denied; stopping collector")
                    return
                except requests.RequestException as exc:
                    logging.error("FR24 request failed for area %d: %s: %s",
                                  area_index, type(exc).__name__, exc)
                except Exception:
                    logging.exception("FR24 request/decode cycle failed for area %d", area_index)

            logging.info(
                "Batch complete: %d feed records; %d aircraft in shared cache; processed %d/%d areas",
                cycle_feeds, len(CACHE.snapshot()), len(selected_areas), len(areas),
            )
            # Avoid a tight loop when no ESP32 requests arrive.
            elapsed = time.monotonic() - cycle_started
            if not AREAS.snapshot():
                time.sleep(max(0.0, INTERVAL_SECONDS - elapsed))
    except KeyboardInterrupt:
        logging.info("Stopping on Ctrl+C")
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        logging.info("FR24 multi-area collector stopped")


if __name__ == "__main__":
    main()
