import unittest
from unittest.mock import Mock

import requests

from upstream_client import UpstreamClient


def response(status=200):
    item = Mock()
    item.status_code = status
    if status >= 400:
        error = requests.HTTPError(f"HTTP {status}")
        error.response = item
        item.raise_for_status.side_effect = error
    return item


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class UpstreamClientTests(unittest.TestCase):
    def make_client(self, session, clock=None, **kwargs):
        clock = clock or FakeClock()
        return UpstreamClient(
            session,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            **kwargs,
        ), clock

    def test_success_uses_configured_timeout(self):
        session = Mock()
        expected = response()
        session.post.return_value = expected
        client, _ = self.make_client(session, timeout_seconds=17)
        self.assertIs(client.post("https://example.test/feed", data=b"x"), expected)
        self.assertEqual(session.post.call_args.kwargs["timeout"], 17)

    def test_network_and_server_errors_retry_with_exponential_backoff(self):
        session = Mock()
        expected = response()
        session.post.side_effect = [
            requests.ConnectionError("offline"),
            response(503),
            expected,
        ]
        client, clock = self.make_client(
            session, max_retries=2, backoff_seconds=1, min_interval_seconds=0
        )
        self.assertIs(client.post("https://example.test/feed"), expected)
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(clock.sleeps, [1, 2])

    def test_http_429_is_retried(self):
        session = Mock()
        expected = response()
        session.post.side_effect = [response(429), expected]
        client, clock = self.make_client(
            session, max_retries=1, backoff_seconds=0.5, min_interval_seconds=0
        )
        self.assertIs(client.post("https://example.test/feed"), expected)
        self.assertEqual(clock.sleeps, [0.5])

    def test_non_transient_client_error_is_not_retried(self):
        session = Mock()
        session.post.return_value = response(400)
        client, _ = self.make_client(session, max_retries=2)
        with self.assertRaises(requests.HTTPError):
            client.post("https://example.test/feed")
        self.assertEqual(session.post.call_count, 1)

    def test_authentication_error_stops_without_retry(self):
        for status in (401, 403):
            with self.subTest(status=status):
                session = Mock()
                session.post.return_value = response(status)
                client, _ = self.make_client(session, max_retries=2)
                with self.assertRaises(PermissionError):
                    client.post("https://example.test/feed")
                self.assertEqual(session.post.call_count, 1)

    def test_retry_count_is_bounded(self):
        session = Mock()
        session.post.side_effect = requests.Timeout("timeout")
        client, clock = self.make_client(
            session, max_retries=2, backoff_seconds=1, min_interval_seconds=0
        )
        with self.assertRaises(requests.Timeout):
            client.post("https://example.test/feed")
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(clock.sleeps, [1, 2])

    def test_minimum_interval_applies_between_all_attempts(self):
        session = Mock()
        session.post.return_value = response()
        client, clock = self.make_client(
            session, min_interval_seconds=0.25, max_retries=0
        )
        client.post("https://example.test/feed")
        client.post("https://example.test/feed")
        self.assertEqual(clock.sleeps, [0.25])


if __name__ == "__main__":
    unittest.main()
