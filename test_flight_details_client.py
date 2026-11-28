import unittest
from unittest.mock import Mock

from flight_details_client import (
    FlightDetailsClient,
    FlightNotFoundError,
    FlightDetailsError,
)


def varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def frame(flag, payload):
    return bytes([flag]) + len(payload).to_bytes(4, "big") + payload


def success_response(icao):
    aircraft_info = b"\x08" + varint(icao)
    response = b"\x0a" + varint(len(aircraft_info)) + aircraft_info
    return frame(0, response) + frame(0x80, b"grpc-status: 0\r\n")


class FlightDetailsTests(unittest.TestCase):
    def setUp(self):
        self.upstream = Mock()
        self.client = FlightDetailsClient(self.upstream, {})

    def test_extract_icao(self):
        response = Mock()
        response.content = success_response(0x71C535)
        response.headers = {}
        self.upstream.post.return_value = response

        self.assertEqual(self.client.get_icao(1120075720), 0x71C535)

    def test_not_found(self):
        response = Mock()
        response.content = frame(0x80, b"grpc-status: 5\r\ngrpc-message: Flight not found!\r\n")
        response.headers = {}
        self.upstream.post.return_value = response

        with self.assertRaises(FlightNotFoundError):
            self.client.get_icao(1120058628)

    def test_invalid_status(self):
        response = Mock()
        response.content = frame(0x80, b"grpc-status: 13\r\n")
        response.headers = {}
        self.upstream.post.return_value = response

        with self.assertRaises(FlightDetailsError):
            self.client.get_icao(1120075720)


if __name__ == "__main__":
    unittest.main(verbosity=2)