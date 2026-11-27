from __future__ import annotations

import logging
import time

import requests


class UpstreamClient:
    """Rate-limited FR24 HTTP client with retries for transient failures only."""

    def __init__(
        self,
        session,
        *,
        min_interval_seconds: float = 0.25,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if backoff_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("backoff_seconds and timeout_seconds must be positive")
        self.session = session
        self.min_interval_seconds = min_interval_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def post(self, url: str, **kwargs):
        """POST once or retry network errors, HTTP 429, and HTTP 5xx responses."""
        kwargs["timeout"] = self.timeout_seconds
        for attempt in range(self.max_retries + 1):
            if self._last_request_at is not None:
                remaining = self.min_interval_seconds - (
                    self._monotonic() - self._last_request_at
                )
                if remaining > 0:
                    self._sleep(remaining)

            self._last_request_at = self._monotonic()
            try:
                response = self.session.post(url, **kwargs)
                status = response.status_code
                if status in (401, 403):
                    raise PermissionError(
                        f"FR24 returned HTTP {status}; check local session configuration"
                    )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                status = (
                    exc.response.status_code
                    if isinstance(exc, requests.HTTPError) and exc.response is not None
                    else None
                )
                transient = status is None or status == 429 or status >= 500
                if not transient or attempt >= self.max_retries:
                    raise
                delay = self.backoff_seconds * (2 ** attempt)
                logging.warning(
                    "FR24 transient upstream failure (%s); retry %d/%d in %.1fs",
                    type(exc).__name__, attempt + 1, self.max_retries, delay,
                )
                self._sleep(delay)
