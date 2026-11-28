import unittest
from unittest.mock import patch

from aircraft_cache import AircraftCache
from model import Feed


class AircraftCacheIcaoTests(unittest.TestCase):
    def setUp(self):
        self.cache = AircraftCache()
        self.now = 1790000000.0
        self.feed = Feed(
            field_1=12345,
            field_2=54.91,
            field_3=82.33,
            field_15=1790000000000,
        )

    def test_missing_icao_candidate_and_set_icao(self):
        with patch("aircraft_cache.time.time", return_value=self.now):
            self.cache.update([self.feed])
            self.assertEqual(self.cache.missing_icao_candidate(), "12345")
            self.assertTrue(self.cache.set_icao("12345", 0x71C535))
            self.assertIsNone(self.cache.missing_icao_candidate())

            aircraft = self.cache.snapshot()[0]
            self.assertEqual(aircraft["icao_address"], 0x71C535)
            self.assertEqual(aircraft["icao_hex"], "71C535")

    def test_icao_survives_later_livefeed_update(self):
        with patch("aircraft_cache.time.time", return_value=self.now):
            self.cache.update([self.feed])
            self.assertTrue(self.cache.set_icao("12345", 0x71C535))
            self.cache.update([self.feed])

            aircraft = self.cache.snapshot()[0]
            self.assertEqual(aircraft["icao_address"], 0x71C535)
            self.assertEqual(aircraft["icao_hex"], "71C535")

    def test_invalid_icao_and_unknown_aircraft_are_rejected(self):
        with patch("aircraft_cache.time.time", return_value=self.now):
            self.cache.update([self.feed])
            for value in (0, -1, 0x1000000, "not-a-number"):
                self.assertFalse(self.cache.set_icao("12345", value))
            self.assertFalse(self.cache.set_icao("missing", 0x71C535))

    def test_candidate_can_be_excluded(self):
        with patch("aircraft_cache.time.time", return_value=self.now):
            self.cache.update([self.feed])
            self.assertIsNone(
                self.cache.missing_icao_candidate(exclude_ids={"12345"})
            )


if __name__ == "__main__":
    unittest.main()
