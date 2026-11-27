import unittest

from area_manager import RadarArea, merge_overlapping_areas


class AreaMergeTests(unittest.TestCase):
    def test_overlapping_areas_merge_into_one_covering_area(self):
        a = RadarArea(0.0, 0.0, 100.0)
        b = RadarArea(0.0, 1.0, 100.0)
        merged = merge_overlapping_areas([a, b])
        self.assertEqual(len(merged), 1)
        center = merged[0]
        # Both source circles must fit inside the resulting enclosing circle.
        from area_manager import _distance_km
        self.assertLessEqual(_distance_km(center, a) + a.radius_km, center.radius_km + 1e-6)
        self.assertLessEqual(_distance_km(center, b) + b.radius_km, center.radius_km + 1e-6)

    def test_distant_areas_remain_separate(self):
        a = RadarArea(0.0, 0.0, 20.0)
        b = RadarArea(0.0, 10.0, 20.0)
        self.assertEqual(len(merge_overlapping_areas([a, b])), 2)

    def test_contained_area_does_not_expand_outer_area(self):
        outer = RadarArea(10.0, 10.0, 100.0)
        inner = RadarArea(10.1, 10.1, 5.0)
        merged = merge_overlapping_areas([outer, inner])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0].radius_km, outer.radius_km)


if __name__ == "__main__":
    unittest.main()
