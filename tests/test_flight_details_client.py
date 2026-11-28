import unittest
from unittest.mock import Mock

from flight_details_client import (
    FlightDetailsClient,
    FlightNotFoundError,
)


def varint(value):
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def length_field(number, value):
    return varint((number << 3) | 2) + varint(len(value)) + value


def make_response(icao):
    # AircraftInfo: icao_address = field 1, varint.
    aircraft_info = varint(8) + varint(icao)

    # FlightDetailsResponse: aircraft_info = field 1, bytes.
    protobuf = length_field(1, aircraft_info)

    # gRPC-Web data frame.
    data_frame = b"\x00" + len(protobuf).to_bytes(4, "big") + protobuf

    # gRPC-Web trailer frame.
    trailer = b"grpc-status: 0\r\n"
    trailer_frame = (
        b"\x80" + len(trailer).to_bytes(4, "big") + trailer
    )

    return data_frame + trailer_frame


class FlightDetailsClientTests(unittest.TestCase):

    def test_extract_icao(self):
        upstream = Mock()
        response = Mock()
        response.headers = {}
        response.content = make_response(7456053)
        upstream.post.return_value = response

        client = FlightDetailsClient(upstream, {})

        result = client.get_icao_address(1120075720)

        self.assertEqual(result, 7456053)
        upstream.post.assert_called_once()

    def test_flight_not_found(self):
        upstream = Mock()
        response = Mock()
        response.headers = {
            "grpc-status": "5",
            "grpc-message": "Flight not found!",
        }
        response.content = b""
        upstream.post.return_value = response

        client = FlightDetailsClient(upstream, {})

        with self.assertRaises(FlightNotFoundError):
            client.get_icao_address(1120058628)


if __name__ == "__main__":
    unittest.main(verbosity=2)