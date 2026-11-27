import time
import unittest

from area_manager import (
    AreaRegistry,
    RadarArea,
    _distance_km,
    merge_overlapping_areas,
)


class AreaMergeTests(unittest.TestCase):
    def assert_area_encloses(self, enclosing, source):
        self.assertLessEqual(
            _distance_km(enclosing, source) + source.radius_km,
            enclosing.radius_km + 1e-6,
        )

    def test_overlapping_areas_merge_into_one_covering_area(self):
        a = RadarArea(0.0, 0.0, 100.0)
        b = RadarArea(0.0, 1.0, 100.0)
        merged = merge_overlapping_areas([a, b])
        self.assertEqual(len(merged), 1)
        self.assert_area_encloses(merged[0], a)
        self.assert_area_encloses(merged[0], b)

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
        self.assert_area_encloses(merged[0], inner)

    def test_overlapping_areas_across_date_line_merge_correctly(self):
        a = RadarArea(0.0, 179.5, 100.0)
        b = RadarArea(0.0, -179.5, 100.0)
        merged = merge_overlapping_areas([a, b])
        self.assertEqual(len(merged), 1)
        self.assert_area_encloses(merged[0], a)
        self.assert_area_encloses(merged[0], b)

    def test_registry_deduplicates_identical_areas(self):
        registry = AreaRegistry(batch_window_seconds=0.0)
        registry.register(54.91001, 82.33001, 50.0)
        registry.register(54.91002, 82.33002, 50.0)
        stats = registry.stats()
        self.assertEqual(stats["registered_areas"], 1)
        self.assertEqual(stats["requests_total"], 2)

    def test_registry_collects_pending_batch(self):
        registry = AreaRegistry(batch_window_seconds=0.01)
        registry.register(54.91, 82.33, 50.0)
        batch = registry.wait_for_batch(timeout=0.01)
        self.assertEqual(len(batch), 1)
        self.assertEqual(registry.stats()["batches_total"], 1)

    def test_registry_expires_inactive_areas(self):
        registry = AreaRegistry(batch_window_seconds=0.0, active_ttl_seconds=0.01)
        registry.register(54.91, 82.33, 50.0)
        time.sleep(0.02)
        self.assertEqual(registry.snapshot(), [])


if __name__ == "__main__":
    unittest.main()
