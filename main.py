from __future__ import annotations

import json
import logging
import math
import time
import queue
import threading
from pathlib import Path

from FlightRadarAPI import FlightRadar24API

from aircraft_cache import CACHE
from api_server import get_active_area, start_api_server
from model import Feed

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "radar_config.json"
LOG_DIR = BASE_DIR / "logs"

INTERVAL_SECONDS = 10
TIMEOUT_SECONDS = 20
API_HOST = "0.0.0.0"
API_PORT = 8765
SOURCE_NAME = "FlightRadarAPI (Flightradar24 website feed)"
DETAIL_TTL_SECONDS = 900
DETAIL_WORKER_MAX_PER_CYCLE = 1
DETAIL_QUEUE: queue.Queue = queue.Queue(maxsize=32)
DETAIL_CACHE: dict[str, tuple[float, dict]] = {}
DETAIL_ATTEMPTED: dict[str, float] = {}
DETAIL_LOCK = threading.RLock()


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


def _number(value):
    """Convert FlightRadarAPI values to numbers; its missing-value sentinel is 'N/A'."""
    if value is None or value == "N/A" or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _text(value):
    if value is None or value == "N/A" or value == "":
        return None
    return str(value)


def _boolean(value):
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True"):
        return True
    if value in (0, "0", "false", "False"):
        return False
    return None


def _detail_text(flight, name: str):
    return _text(getattr(flight, name, None))


def _detail_worker() -> None:
    """Fetch a few flight-detail records in the background; never block live-feed polling."""
    detail_api = FlightRadar24API(timeout=TIMEOUT_SECONDS)
    while True:
        flight = DETAIL_QUEUE.get()
        try:
            details = detail_api.get_flight_details(flight)
            if details:
                flight.set_flight_details(details)
                names = (
                    "airline_name", "airline_short_name",
                    "origin_airport_name", "origin_airport_icao",
                    "origin_airport_country_name", "origin_airport_country_code",
                    "destination_airport_name", "destination_airport_icao",
                    "destination_airport_country_name", "destination_airport_country_code",
                    "aircraft_model", "status_text",
                )
                values = {name: _detail_text(flight, name) for name in names}
                values = {name: value for name, value in values.items() if value}
                with DETAIL_LOCK:
                    DETAIL_CACHE[str(flight.id)] = (time.monotonic(), values)
                logging.info("Flight details cached for %s (%d fields)", flight.id, len(values))
        except Exception as exc:
            logging.warning("Flight details request failed for %s: %s", getattr(flight, "id", "?"), exc)
        finally:
            DETAIL_QUEUE.task_done()
            time.sleep(20)


def _queue_flight_details(flights) -> int:
    queued = 0
    now = time.monotonic()
    with DETAIL_LOCK:
        expired_details = [key for key, (stamp, _) in DETAIL_CACHE.items() if now - stamp > DETAIL_TTL_SECONDS * 4]
        for key in expired_details:
            DETAIL_CACHE.pop(key, None)
    for flight in flights:
        if queued >= DETAIL_WORKER_MAX_PER_CYCLE:
            break
        flight_id = str(getattr(flight, "id", "") or "")
        if not flight_id:
            continue
        with DETAIL_LOCK:
            if len(DETAIL_ATTEMPTED) > 500:
                expired = [key for key, stamp in DETAIL_ATTEMPTED.items() if now - stamp > 3600]
                for key in expired:
                    DETAIL_ATTEMPTED.pop(key, None)
            cached = DETAIL_CACHE.get(flight_id)
            attempted = DETAIL_ATTEMPTED.get(flight_id, 0.0)
            if cached and now - cached[0] < DETAIL_TTL_SECONDS:
                continue
            if now - attempted < DETAIL_TTL_SECONDS:
                continue
            DETAIL_ATTEMPTED[flight_id] = now
        try:
            DETAIL_QUEUE.put_nowait(flight)
            queued += 1
        except queue.Full:
            with DETAIL_LOCK:
                DETAIL_ATTEMPTED.pop(flight_id, None)
            break
    return queued


def normalize_flight(flight) -> Feed | None:
    """Map public FlightRadarAPI flight fields into the existing cache model."""
    latitude = _number(flight.latitude)
    longitude = _number(flight.longitude)
    stamp = _number(flight.time)
    if latitude is None or longitude is None or stamp is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    stamp_ms = int(stamp * 1000) if stamp < 100_000_000_000 else int(stamp)
    altitude = _number(flight.altitude)
    speed = _number(flight.ground_speed)
    heading = _number(flight.heading)
    vertical_speed = _number(flight.vertical_speed)

    with DETAIL_LOCK:
        cached_details = DETAIL_CACHE.get(str(flight.id))
        details = cached_details[1] if cached_details else {}

    return Feed(
        field_1=str(flight.id),
        field_2=latitude,
        field_3=longitude,
        field_4=int(heading) % 360 if heading is not None else None,
        field_5=int(altitude) if altitude is not None else None,
        field_6=int(speed) if speed is not None else None,
        field_10=_boolean(flight.on_ground),
        field_9=int(stamp),
        field_11=_text(flight.callsign),
        field_15=stamp_ms,
        flight_number=_text(flight.number),
        registration=_text(flight.registration),
        origin=_text(flight.origin_airport_iata),
        destination=_text(flight.destination_airport_iata),
        aircraft_type=_text(flight.aircraft_code),
        squawk=int(_number(flight.squawk)) if _number(flight.squawk) is not None else None,
        vertical_speed_fpm=int(vertical_speed) if vertical_speed is not None else None,
        icao_hex=_text(flight.icao_24bit),
        airline_icao=_text(flight.airline_icao),
        airline_iata=_text(flight.airline_iata),
        airline_name=details.get("airline_name"),
        airline_short_name=details.get("airline_short_name"),
        origin_name=details.get("origin_airport_name"),
        origin_icao=details.get("origin_airport_icao"),
        origin_country=details.get("origin_airport_country_name"),
        origin_country_code=details.get("origin_airport_country_code"),
        destination_name=details.get("destination_airport_name"),
        destination_icao=details.get("destination_airport_icao"),
        destination_country=details.get("destination_airport_country_name"),
        destination_country_code=details.get("destination_airport_country_code"),
        aircraft_model=details.get("aircraft_model"),
        status_text=details.get("status_text"),
    )


def main() -> None:
    setup_logging()
    config = load_config()
    server = start_api_server(API_HOST, API_PORT)
    threading.Thread(target=_detail_worker, name="FR24Details", daemon=True).start()
    fr_api = FlightRadar24API(timeout=TIMEOUT_SECONDS)

    logging.info("FR24 Standard API collector started; source: %s", SOURCE_NAME)
    logging.info(
        "Radar center %.5f, %.5f; radius %.1f km; API http://%s:%d",
        config["latitude"], config["longitude"], config["radius_km"], API_HOST, API_PORT,
    )
    logging.info("Polling interval: %d seconds", INTERVAL_SECONDS)
    logging.info("No FR24 account credentials or API key are configured.")

    request_index = 0
    try:
        while True:
            started = time.monotonic()
            request_index += 1
            try:
                active_area = get_active_area(config)
                bounds = fr_api.get_bounds_by_point(
                    active_area["latitude"],
                    active_area["longitude"],
                    active_area["radius_km"] * 1000,
                )
                flights = fr_api.get_flights(bounds=bounds)
                _queue_flight_details(flights)
                feeds = [
                    normalized
                    for flight in flights
                    if (normalized := normalize_flight(flight)) is not None
                ]

                CACHE.update(
                    feeds,
                    source_stats=[{"flight_count": len(flights), "normalized_count": len(feeds)}],
                    response_protobuf=[],
                    source_name=SOURCE_NAME,
                )
                logging.info(
                    "Request #%d: received %d FR24 flights, normalized %d; cache %d aircraft; radar %.5f, %.5f / %.1f km",
                    request_index, len(flights), len(feeds), len(CACHE.snapshot()),
                    active_area["latitude"], active_area["longitude"], active_area["radius_km"],
                )
            except Exception as exc:
                logging.exception("FlightRadarAPI request #%d failed: %s", request_index, exc)

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
