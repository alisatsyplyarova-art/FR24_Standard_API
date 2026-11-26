import struct
import unittest

from analysis_context import AnalysisContext
from feed_decoder import decode_feed
from model import SourceRef
from protobuf_parser import encode_varint, int32_decode


MASK64 = (1 << 64) - 1


def varint_field(number: int, value: int) -> bytes:
    return encode_varint((number << 3) | 0) + encode_varint(value & MASK64)


def bytes_field(number: int, value: bytes) -> bytes:
    return encode_varint((number << 3) | 2) + encode_varint(len(value)) + value


def string_field(number: int, value: str) -> bytes:
    return bytes_field(number, value.encode("utf-8"))


def fixed32_field(number: int, value: float) -> bytes:
    return encode_varint((number << 3) | 5) + struct.pack("<f", value)


class Int32DecodeTests(unittest.TestCase):
    def test_signed_int32_twos_complement(self):
        self.assertEqual(int32_decode(0), 0)
        self.assertEqual(int32_decode(123), 123)
        self.assertEqual(int32_decode(0xFFFFFFFF), -1)
        self.assertEqual(int32_decode(0xFFFFFF00), -256)
        self.assertEqual(int32_decode(MASK64 - 639), -640)


class LiveFeedSchemaTests(unittest.TestCase):
    def test_extra_info_ems_and_ems_availability_are_separate(self):
        route = (
            string_field(1, "AAA")
            + string_field(2, "BBB")
            + string_field(3, "CCC")
        )
        schedule = (
            varint_field(1, 1760000000)
            + varint_field(2, 1760000300)
            + varint_field(7, 65)
        )
        ems = (
            varint_field(1, 1013)
            + varint_field(4, -15)
            + varint_field(5, 240)
            + varint_field(7, 704)
        )
        ems_availability = (
            varint_field(1, 1)
            + varint_field(4, 1)
            + varint_field(5, 0)
            + varint_field(7, 1)
        )
        extra = (
            string_field(1, "AB123")
            + string_field(2, "N123AB")
            + bytes_field(3, route)
            + string_field(4, "B738")
            + varint_field(5, 7500)
            + varint_field(6, -640)
            + bytes_field(9, schedule)
            + bytes_field(12, ems)
            + bytes_field(13, ems_availability)
            + varint_field(14, 0xABCDEF)
            + varint_field(15, 1234)
            + varint_field(16, 1)
        )
        feed_bytes = (
            varint_field(1, 987654321)
            + fixed32_field(2, 54.91)
            + fixed32_field(3, 82.33)
            + varint_field(4, 270)
            + varint_field(5, 12000)
            + varint_field(6, 420)
            + varint_field(9, 1760000000)
            + varint_field(15, 1760000000123)
            + bytes_field(13, extra)
        )

        feed = decode_feed(
            feed_bytes,
            SourceRef(0, 0, 0),
            AnalysisContext(),
        )

        self.assertEqual(feed.flight_number, "AB123")
        self.assertEqual(feed.registration, "N123AB")
        self.assertEqual(feed.origin, "AAA")
        self.assertEqual(feed.destination, "BBB")
        self.assertEqual(feed.diverted_to, "CCC")
        self.assertEqual(feed.vertical_speed_fpm, -640)
        self.assertEqual(feed.schedule["std"], 1760000000)
        self.assertEqual(feed.schedule["progress_pct"], 65)
        self.assertEqual(feed.ems_info["qnh"], 1013)
        self.assertEqual(feed.ems_info["oat"], -15)
        self.assertEqual(feed.ems_info["mach"], 704)
        self.assertEqual(feed.ems_availability["qnh"], True)
        self.assertEqual(feed.ems_availability["oat"], True)
        self.assertEqual(feed.ems_availability["ias"], False)
        self.assertEqual(feed.icao_hex, "ABCDEF")
        self.assertEqual(feed.field_9, 1760000000)


if __name__ == "__main__":
    unittest.main()
