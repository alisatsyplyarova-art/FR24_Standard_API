#!/usr/bin/env python3
"""Concurrent API load probe for 10, 50, or 100 ESP32-like clients.

This script sends only ordinary radar-area GET requests. It never reads or sends
HAR files, cookies, authorization headers, or FR24 session material.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_once(base_url: str, client_id: int, request_timeout: float) -> tuple[float, str | None]:
    lat = -45.0 + (client_id % 10) * 10.0
    lon = -150.0 + (client_id // 10) * 30.0
    url = f"{base_url.rstrip('/')}/v2/lat/{lat:.4f}/lon/{lon:.4f}/dist/25"
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "FR24-API-load-test/1.0"})
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=request_timeout) as response:
            if response.status != 200:
                return time.perf_counter() - started, f"HTTP {response.status}"
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload.get("ac"), list):
            return time.perf_counter() - started, "missing ac[]"
        required = ("msg", "now", "ctime", "total", "ptime")
        if any(key not in payload for key in required):
            return time.perf_counter() - started, "missing response contract field"
        if payload["total"] != len(payload["ac"]):
            return time.perf_counter() - started, "total does not match ac length"
        for aircraft in payload["ac"]:
            if not all(key in aircraft for key in ("fr24_id", "lat", "lon", "seen", "seen_pos")):
                return time.perf_counter() - started, "aircraft missing required field"
        return time.perf_counter() - started, None
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return time.perf_counter() - started, f"{type(exc).__name__}: {exc}"


def run_stage(base_url: str, clients: int, requests_per_client: int, timeout: float) -> dict:
    jobs = [client for client in range(clients) for _ in range(requests_per_client)]
    started = time.perf_counter()
    latencies = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
        futures = [pool.submit(request_once, base_url, client, timeout) for client in jobs]
        for future in concurrent.futures.as_completed(futures):
            elapsed, error = future.result()
            latencies.append(elapsed)
            if error:
                errors.append(error)
    duration = time.perf_counter() - started
    ordered = sorted(latencies)

    def percentile(p: float) -> float:
        if not ordered:
            return 0.0
        index = min(len(ordered) - 1, round((len(ordered) - 1) * p))
        return ordered[index] * 1000

    return {
        "clients": clients,
        "requests": len(jobs),
        "duration_seconds": round(duration, 3),
        "requests_per_second": round(len(jobs) / duration, 2) if duration else 0,
        "latency_ms": {
            "min": round(min(ordered) * 1000, 2) if ordered else 0,
            "p50": round(statistics.median(ordered) * 1000, 2) if ordered else 0,
            "p95": round(percentile(0.95), 2),
            "p99": round(percentile(0.99), 2),
            "max": round(max(ordered) * 1000, 2) if ordered else 0,
        },
        "errors": len(errors),
        "error_samples": errors[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Base URL of the running API")
    parser.add_argument("--clients", nargs="+", type=int, default=[10, 50, 100])
    parser.add_argument("--requests-per-client", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    if any(value < 1 or value > 500 for value in args.clients):
        parser.error("client counts must be between 1 and 500")
    if args.requests_per_client < 1 or args.timeout <= 0:
        parser.error("requests-per-client and timeout must be positive")

    print("FR24 Standard API load test (no upstream FR24 requests are generated)")
    results = [
        run_stage(args.url, count, args.requests_per_client, args.timeout)
        for count in args.clients
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(item["errors"] for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
