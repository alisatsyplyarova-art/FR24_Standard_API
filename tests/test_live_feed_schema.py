import struct
import unittest

from analysis_context import AnalysisContext
from feed_decoder import decode_feed_response
from model import SourceRef


def varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def vfield(number: int, value: int) -> bytes:
    return varint(number << 3) + varint(value)


def lfield(number: int, payload: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(payload)) + payload


class LiveFeedSchemaTests(unittest.TestCase):
    def test_selected_flight_ems_availability_stats_and_server_time(self):
        # ExtraFlightInfo.field_13 = EMSAvailability:
        # qnh_availability=true, ias_availability=false.
        ems_availability = vfield(1, 1) + vfield(5, 0)
        extra = lfield(13, ems_availability)
        feed = (
            vfield(1, 12345)
            + varint((2 << 3) | 5) + struct.pack("<f", 54.91)
            + varint((3 << 3) | 5) + struct.pack("<f", 82.33)
            + lfield(13, extra)
            + vfield(15, 1790000000000)
        )

        # Stats.total_list contains one SourceStats { source=ADSB, count=7 }.
        source_stats = vfield(1, 0) + vfield(2, 7)
        stats = lfield(1, source_stats)
        response = (
            lfield(3, feed)
            + lfield(2, stats)
            + vfield(4, 1790000000123)
        )

        decoded = decode_feed_response(
            response,
            SourceRef(http_record_index=1, frame_index=0, protobuf_message_index=0),
            AnalysisContext(),
        )

        self.assertEqual(len(decoded.feeds), 0)
        self.assertEqual(len(decoded.selected_feeds), 1)
        selected = decoded.selected_feeds[0]
        self.assertEqual(selected.field_1, 12345)
        self.assertEqual(selected.ems_availability["qnh"], True)
        self.assertEqual(selected.ems_availability["ias"], False)
        self.assertEqual(decoded.stats, [{"source": 0, "count": 7}])
        self.assertEqual(decoded.server_time_ms, 1790000000123)


if __name__ == "__main__":
    unittest.main()
