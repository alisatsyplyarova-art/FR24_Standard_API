import json
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

import api_server


class ApiServerTests(unittest.TestCase):
    def setUp(self):
        api_server._RESPONSE_CACHE.clear()
        self.cache_patch = patch.object(api_server.CACHE, "snapshot", return_value=[
            {
                "id": "ABC123",
                "callsign": "TEST123",
                "current": {
                    "latitude": 54.91,
                    "longitude": 82.33,
                    "timestamp": 1_798_000_000_000,
                },
                "last_seen": 1_798_000_000.0,
                "heading": 270.0,
                "track": 270,
                "altitude_ft": 32000,
                "speed_kt": 450,
                "on_ground": False,
                "aircraft_type": "A320",
                "icao_hex": "ABC123",
            },
            {
                "id": "FAR456",
                "callsign": "FAR456",
                "current": {
                    "latitude": 55.5,
                    "longitude": 83.5,
                    "timestamp": 1_798_000_000_000,
                },
                "last_seen": 1_798_000_000.0,
                "heading": None,
            },
        ])
        self.register_patch = patch.object(api_server.AREAS, "register")
        self.cache_patch.start()
        self.register_patch.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server._Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.cache_patch.stop()
        self.register_patch.stop()
        api_server._RESPONSE_CACHE.clear()

    def get_json(self, path):
        with urlopen(self.base_url + path, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_legacy_route_returns_expected_protocol_and_filters_by_radius(self):
        status, payload = self.get_json("/v2/lat/54.91/lon/82.33/dist/50")
        self.assertEqual(status, 200)
        self.assertEqual(
            set(("ac", "msg", "now", "total", "ctime", "ptime")),
            set(payload),
        )
        self.assertEqual(payload["msg"], "No error")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["ac"][0]["fr24_id"], "ABC123")
        self.assertEqual(payload["ac"][0]["flight"], "TEST123")
        self.assertEqual(payload["ac"][0]["track"], 270.0)
        self.assertEqual(payload["ac"][0]["altitude_ft"], 32000)
        self.assertEqual(payload["ac"][0]["speed_kt"], 450)
        self.assertIs(payload["ac"][0]["on_ground"], False)
        self.assertEqual(payload["ac"][0]["aircraft_type"], "A320")
        self.assertEqual(payload["ac"][0]["hex"], "ABC123")
        api_server.AREAS.register.assert_called_once_with(54.91, 82.33, 50.0)

    def test_flight_radar_d_clock_1135_required_json_contract(self):
        _, payload = self.get_json("/v2/lat/54.91/lon/82.33/dist/50")
        self.assertIsInstance(payload["ac"], list)
        self.assertIsInstance(payload["total"], int)
        self.assertIsInstance(payload["now"], int)
        self.assertIsInstance(payload["ctime"], int)
        self.assertEqual(payload["total"], len(payload["ac"]))
        aircraft = payload["ac"][0]
        self.assertIsInstance(aircraft["fr24_id"], str)
        self.assertIsInstance(aircraft["lat"], (int, float))
        self.assertIsInstance(aircraft["lon"], (int, float))
        self.assertIsInstance(aircraft["seen"], (int, float))
        self.assertIsInstance(aircraft["seen_pos"], (int, float))
        self.assertGreaterEqual(aircraft["seen_pos"], 0)
        if "flight" in aircraft:
            self.assertIsInstance(aircraft["flight"], str)
        if "track" in aircraft:
            self.assertIsInstance(aircraft["track"], (int, float))

    def test_invalid_coordinates_are_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base_url + "/v2/lat/91/lon/82.33/dist/50", timeout=3)
        self.assertEqual(caught.exception.code, 400)

    def test_unknown_route_returns_404(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base_url + "/v2/lat/54.91/lon/82.33/range/50", timeout=3)
        self.assertEqual(caught.exception.code, 404)

    def test_response_cache_expires_after_ttl(self):
        key = (54.91, 82.33, 50.0)
        payload = {"total": 7}
        api_server._store_response(key, 100.0, payload)
        self.assertEqual(api_server._cached_response(key, 104.9), payload)
        self.assertIsNone(api_server._cached_response(key, 105.1))


if __name__ == "__main__":
    unittest.main()
