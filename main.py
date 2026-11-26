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
from api_server import get_active_area, start_api_server
from feed_decoder import decode_feed_response
from grpc_web import decode_grpc_web_body
from model import SourceRef

BASE_DIR = Path(__file__).resolve().parent
HAR_FILE = BASE_DIR / "www.flightradar24.com.har"
CONFIG_FILE = BASE_DIR / "radar_config.json"
CAPTURE_DIR = BASE_DIR / "captures"
LOG_DIR = BASE_DIR / "logs"

URL = "https://data-feed.flightradar24.com/fr24.feed.api.v1.Feed/LiveFeed"
INTERVAL_SECONDS = 10
TIMEOUT_SECONDS = 20
API_HOST = "0.0.0.0"
API_PORT = 8765

ALLOWED_HEADERS = {
    "content-type",
    "x-grpc-web",
    "x-user-agent",
    "fr24-device-id",
    "fr24-platform",
    "origin",
    "referer",
    "user-agent",
    "accept",
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

    lat = float(config["latitude"])
    lon = float(config["longitude"])
    radius_km = float(config["radius_km"])
    if not all(math.isfinite(v) for v in (lat, lon, radius_km)):
        raise ValueError("Radar settings must be finite numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinates are out of range")
    if not (0 < radius_km <= 20000):
        raise ValueError("Radius must be between 0 and 20000 km")
    return {"latitude": lat, "longitude": lon, "radius_km": radius_km}


def build_request_body(template: bytes, config: dict | None = None) -> bytes:
    # Если ESP32 уже присылал запрос, используем его центр и радиус.
    # radar_config.json остаётся только начальной областью до первого запроса.
    config = config or load_config()
    lat = config["latitude"]
    lon = config["longitude"]
    radius_km = config["radius_km"]

    angular = radius_km / 6371.0088
    lat_delta = math.degrees(angular)
    north = min(90.0, lat + lat_delta)
    south = max(-90.0, lat - lat_delta)
    if abs(lat) + lat_delta >= 90:
        lon_delta = 180.0
    else:
        ratio = math.sin(angular) / math.cos(math.radians(lat))
        lon_delta = math.degrees(math.asin(min(1.0, max(-1.0, ratio))))

    west = lon - lon_delta
    east = lon + lon_delta
    if west < -180 or east > 180:
        raise ValueError("Configured radar area crosses the date line; adjust longitude/radius")

    result = bytearray(template)
    if (
        len(result) != 70
        or result[:7] != bytes((0, 0, 0, 0, 65, 10, 20))
        or [result[i] for i in (7, 12, 17, 22)] != [13, 21, 29, 37]
    ):
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
    entry = next(
        (
            item
            for item in entries
            if item.get("request", {}).get("url") == URL
            and item.get("request", {}).get("method") == "POST"
            and item.get("request", {}).get("postData", {}).get("text")
        ),
        None,
    )
    if entry is None:
        raise RuntimeError("POST LiveFeed request was not found in HAR")

    request = entry["request"]
    body = request["postData"]["text"].encode("latin1")
    headers = {
        header["name"]: header["value"]
        for header in request.get("headers", [])
        if header.get("name", "").lower() in ALLOWED_HEADERS
    }
    if not body or not headers:
        raise RuntimeError("HAR LiveFeed request is missing its body or allowed headers")
    return body, headers


def decode_response(data: bytes, request_index: int) -> tuple[list, list[str]]:
    frames = decode_grpc_web_body(data)
    feeds = []
    errors = []

    for frame_index, frame in enumerate(frames):
        if not frame.is_data:
            continue
        if frame.is_compressed:
            errors.append(f"frame {frame_index}: compressed payload skipped")
            continue
        source = SourceRef(
            http_record_index=request_index,
            frame_index=frame_index,
            protobuf_message_index=0,
        )
        try:
            result = decode_feed_response(frame.payload, source, AnalysisContext())
            feeds.extend(result.feeds)
            feeds.extend(result.selected_feeds)
        except Exception as exc:
            errors.append(f"frame {frame_index}: {type(exc).__name__}: {exc}")

    return feeds, errors


def main() -> None:
    setup_logging()
    config = load_config()
    template, headers = load_request_template()
    # Validate the template/config before opening the API listener.
    build_request_body(template)

    server = start_api_server(API_HOST, API_PORT)
    session = requests.Session()
    request_index = 0
    logging.info("FR24 Standard API collector started")
    logging.info(
        "Radar center %.5f, %.5f; radius %.1f km; API http://%s:%d",
        config["latitude"], config["longitude"], config["radius_km"], API_HOST, API_PORT,
    )
    logging.info("Polling interval: %d seconds", INTERVAL_SECONDS)

    try:
        while True:
            started = time.monotonic()
            request_index += 1
            try:
                active_area = get_active_area(config)
                response = session.post(
                    URL,
                    data=build_request_body(template, active_area),
                    headers=headers,
                    timeout=TIMEOUT_SECONDS,
                )
                logging.info(
                    "Request #%d: HTTP %d, %d bytes; radar %.5f, %.5f / %.1f km",
                    request_index, response.status_code, len(response.content),
                    active_area["latitude"], active_area["longitude"], active_area["radius_km"],
                )

                if response.status_code in (401, 403):
                    logging.error("FR24 returned HTTP %d; stopping collector (access denied)", response.status_code)
                    break
                response.raise_for_status()

                if not response.content:
                    logging.warning("Request #%d returned an empty body", request_index)
                else:
                    # Optional raw capture for diagnostics; disabled unless explicitly enabled in config.
                    if bool(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")).get("save_captures", False)):
                        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                        (CAPTURE_DIR / f"live_{stamp}.bin").write_bytes(response.content)

                    feeds, errors = decode_response(response.content, request_index)
                    CACHE.update(feeds)
                    logging.info("Request #%d: decoded %d feeds; cache currently %d aircraft", request_index, len(feeds), len(CACHE.snapshot()))
                    for error in errors[:5]:
                        logging.warning("Decode warning: %s", error)

            except requests.RequestException as exc:
                logging.error("HTTP request failed: %s: %s", type(exc).__name__, exc)
            except Exception:
                logging.exception("Request/decode cycle failed")

            delay = max(0.0, INTERVAL_SECONDS - (time.monotonic() - started))
            time.sleep(delay)

    except KeyboardInterrupt:
        logging.info("Stopping on Ctrl+C")
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        logging.info("FR24 Standard API collector stopped")


if __name__ == "__main__":
    main()

