from __future__ import annotations
import json
import struct
import sys
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from grpc_web import decode_grpc_web_body
from protobuf_parser import iter_fields

HAR = BASE / "www.flightradar24.com.har"
URL = "https://data-feed.flightradar24.com/fr24.feed.api.v1.Feed/FlightDetails"
FLIGHT_ID = 1120075720
ALLOWED = {
    "content-type", "x-grpc-web", "x-user-agent", "fr24-device-id",
    "fr24-platform", "origin", "referer", "user-agent", "accept",
}

def main():
    with HAR.open("r", encoding="utf-8-sig") as f:
        har = json.load(f)
    entries = har.get("log", {}).get("entries", [])
    entry = next((e for e in entries
        if e.get("request", {}).get("url", "").endswith("/LiveFeed")
        and e.get("request", {}).get("method") == "POST"), None)
    if entry is None:
        raise RuntimeError("LiveFeed request not found in HAR")
    headers = {h["name"]: h["value"]
        for h in entry["request"].get("headers", [])
        if h.get("name", "").lower() in ALLOWED}
    protobuf = b"\x0d" + struct.pack("<I", FLIGHT_ID) + b"\x18\x01"
    body = b"\x00" + len(protobuf).to_bytes(4, "big") + protobuf
    print("Flight ID:", FLIGHT_ID)
    print("Sending one FlightDetails request...")
    with requests.Session() as session:
        response = session.post(URL, data=body, headers=headers, timeout=20)
    print("HTTP status:", response.status_code)
    print("Content-Type:", response.headers.get("Content-Type", "(missing)"))
    print("Response bytes:", len(response.content))
    print("Diagnostic headers:", {k:v for k,v in response.headers.items() if k.lower() in ("grpc-status", "grpc-message", "content-length", "transfer-encoding", "server")})
    if not response.ok:
        print("HTTP error; response body hidden.")
        return
    try:
        frames = decode_grpc_web_body(response.content)
    except Exception as exc:
        print("gRPC-Web decode error:", type(exc).__name__, str(exc))
        return
    for i, frame in enumerate(frames):
        print(f"Frame {i}: flag=0x{frame.flag:02X}, bytes={frame.length}")
        if frame.is_trailer:
            trailer = frame.payload.decode("ascii", errors="replace")
            for line in trailer.splitlines():
                if line.lower().startswith(("grpc-status:", "grpc-message:")):
                    print("Trailer:", line)
            continue
        if frame.is_compressed:
            print("Compressed frame; skipped.")
            continue
        try:
            response_fields = list(iter_fields(frame.payload))
            aircraft_info = next((bytes(f.value) for f in response_fields
                if f.number == 1 and f.wire_type == 2), None)
            if aircraft_info is None:
                print("AircraftInfo field absent.")
                continue
            aircraft_fields = list(iter_fields(aircraft_info))
            icao = next((int(f.value) for f in aircraft_fields
                if f.number == 1 and f.wire_type == 0), None)
            if icao is None:
                print("ICAO field absent.")
            else:
                print("ICAO decimal:", icao)
                print("ICAO hex:", f"{icao:06X}")
        except Exception as exc:
            print("Protobuf decode error:", type(exc).__name__, str(exc))

if __name__ == "__main__":
    main()
