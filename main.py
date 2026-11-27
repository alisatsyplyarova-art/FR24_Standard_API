from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

from FlightRadarAPI import FlightRadar24API

from aircraft_cache import CACHE
from api_server import get_active_area, start_api_server

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "radar_config.json"
LOG_DIR = BASE_DIR / "logs"

INTERVAL_SECONDS = 10
TIMEOUT_SECONDS = 20
API_HOST = "0.0.0.0"
API_PORT = 8765


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


def main() -> None:
    setup_logging()
    config = load_config()

    # FlightRadarAPI reads the public FR24 live feed; no FR24 API key is used.
    fr_api = FlightRadar24API(timeout=TIMEOUT_SECONDS)
    server = start_api_server(API_HOST, API_PORT)

    logging.info("FR24 Standard API collector started (source: FlightRadarAPI)")
    logging.info(
        "Radar center %.5f, %.5f; radius %.1f km; API http://%s:%d",
        config["latitude"], config["longitude"], config["radius_km"], API_HOST, API_PORT,
    )
    logging.info("Polling interval: %d seconds", INTERVAL_SECONDS)

    try:
        while True:
            started = time.monotonic()
            try:
                # The ESP32 may change the radar area through the existing API.
                active_area = get_active_area(config) or config
                radius_m = float(active_area["radius_km"]) * 1000.0
                bounds = fr_api.get_bounds_by_point(
                    float(active_area["latitude"]),
                    float(active_area["longitude"]),
                    radius_m,
                )
                flights = fr_api.get_flights(bounds=bounds)
                CACHE.update(flights)

                logging.info(
                    "FR24 FlightRadarAPI: received %d flights; cache currently %d aircraft; "
                    "radar %.5f, %.5f / %.1f km",
                    len(flights), len(CACHE.snapshot()),
                    active_area["latitude"], active_area["longitude"], active_area["radius_km"],
                )

            except Exception as exc:
                # Keep the HTTP API alive and retry on the next polling cycle.
                logging.warning(
                    "FlightRadarAPI request failed: %s: %s",
                    type(exc).__name__, exc,
                )

            delay = max(0.0, INTERVAL_SECONDS - (time.monotonic() - started))
            time.sleep(delay)

    except KeyboardInterrupt:
        logging.info("Stopping on Ctrl+C")
    finally:
        server.shutdown()
        server.server_close()
        logging.info("FR24 Standard API collector stopped")


if __name__ == "__main__":
    main()
