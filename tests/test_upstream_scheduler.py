import unittest

from area_manager import RadarArea
from upstream_scheduler import AreaScheduler


class AreaSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.areas = [
            RadarArea(0.0, float(index), 10.0)
            for index in range(5)
        ]

    def test_limit_is_respected(self):
        scheduler = AreaScheduler()
        selected = scheduler.select(self.areas, 2)
        self.assertEqual(len(selected), 2)

    def test_round_robin_eventually_services_every_area(self):
        scheduler = AreaScheduler()
        seen = []
        for _ in range(3):
            seen.extend(scheduler.select(self.areas, 2))
        self.assertEqual(
            {(a.latitude, a.longitude, a.radius_km) for a in seen},
            {(a.latitude, a.longitude, a.radius_km) for a in self.areas},
        )

    def test_rotation_continues_between_cycles(self):
        scheduler = AreaScheduler()
        first = scheduler.select(self.areas, 2)
        second = scheduler.select(self.areas, 2)
        self.assertEqual([a.longitude for a in first], [0.0, 1.0])
        self.assertEqual([a.longitude for a in second], [2.0, 3.0])

    def test_duplicate_areas_are_deduplicated(self):
        scheduler = AreaScheduler()
        duplicated = [self.areas[0], self.areas[0], self.areas[1]]
        selected = scheduler.select(duplicated, 10)
        self.assertEqual(len(selected), 2)

    def test_invalid_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            AreaScheduler().select(self.areas, 0)


if __name__ == "__main__":
    unittest.main()
