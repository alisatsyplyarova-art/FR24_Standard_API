import unittest
from unittest.mock import patch

from aircraft_cache import AircraftCache
from model import Feed


class AircraftCacheMetadataTests(unittest.TestCase):
    def test_feed_metadata_survives_cache_snapshot(self):
        cache = AircraftCache()
        now = 1790000000.0
        feed = Feed(
            field_1=12345,
            field_2=54.91,
            field_3=82.33,
            field_4=270,
            field_5=32000,
            field_6=450,
            field_7=1,
            field_8=4,
            field_10=False,
            field_11="SU123",
            field_12=0,
            field_15=1790000000000,
            aircraft_type="A320",
            registration="RA-12345",
            origin="OVB",
            destination="SVO",
            icao_address=0xABC123,
            icao_hex="ABC123",
        )
        with patch("aircraft_cache.time.time", return_value=now):
            cache.update([feed])
            result = cache.snapshot()

        self.assertEqual(len(result), 1)
        aircraft = result[0]
        self.assertEqual(aircraft["track"], 270)
        self.assertEqual(aircraft["altitude_ft"], 32000)
        self.assertEqual(aircraft["speed_kt"], 450)
        self.assertIs(aircraft["on_ground"], False)
        self.assertEqual(aircraft["aircraft_type"], "A320")
        self.assertEqual(aircraft["registration"], "RA-12345")
        self.assertEqual(aircraft["origin"], "OVB")
        self.assertEqual(aircraft["destination"], "SVO")
        self.assertEqual(aircraft["icao_hex"], "ABC123")


if __name__ == "__main__":
    unittest.main()
