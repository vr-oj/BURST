import json
import unittest

from buti_app.utils.roi import (
    add_crop_to_description,
    bounds_to_normalized_roi,
    normalized_roi_to_bounds,
    pixel_roi_to_bounds,
)


class NormalizedRoiToBoundsTests(unittest.TestCase):
    def test_maps_normalized_coordinates_to_source_pixels(self):
        self.assertEqual(
            normalized_roi_to_bounds((0.25, 0.2, 0.75, 0.6), (500, 1000)),
            (250, 100, 750, 300),
        )

    def test_clamps_roi_to_the_source_frame(self):
        self.assertEqual(
            normalized_roi_to_bounds((-0.1, -0.2, 0.3, 1.2), (500, 1000)),
            (0, 0, 300, 500),
        )

    def test_normalizes_reverse_drag_coordinates(self):
        self.assertEqual(
            normalized_roi_to_bounds((0.75, 0.6, 0.25, 0.2), (500, 1000)),
            (250, 100, 750, 300),
        )

    def test_rejects_empty_or_outside_roi(self):
        self.assertIsNone(
            normalized_roi_to_bounds((0.2, 0.2, 0.2, 0.8), (500, 1000))
        )
        self.assertIsNone(
            normalized_roi_to_bounds((1.1, 1.1, 1.2, 1.2), (500, 1000))
        )

    def test_manual_pixel_bounds_round_trip_exactly(self):
        bounds = (37, 72, 128, 125)
        normalized = bounds_to_normalized_roi(bounds, (480, 640))

        self.assertEqual(
            normalized_roi_to_bounds(normalized, (480, 640)),
            bounds,
        )


class PixelRoiTests(unittest.TestCase):
    def test_converts_position_and_size_to_exclusive_bounds(self):
        self.assertEqual(
            pixel_roi_to_bounds(10, 20, 100, 80, (480, 640)),
            (10, 20, 110, 100),
        )

    def test_rejects_roi_that_does_not_fit_source(self):
        with self.assertRaisesRegex(ValueError, "does not fit"):
            pixel_roi_to_bounds(600, 450, 100, 50, (480, 640))

    def test_rejects_empty_roi(self):
        with self.assertRaisesRegex(ValueError, "at least 1 pixel"):
            pixel_roi_to_bounds(0, 0, 0, 10, (480, 640))


class CropDescriptionTests(unittest.TestCase):
    def test_preserves_burst_metadata_and_adds_crop_provenance(self):
        original = json.dumps({"frameIdx": 7, "force": 12.5})
        result = json.loads(
            add_crop_to_description(original, (10, 20, 110, 220), (480, 640))
        )

        self.assertEqual(result["frameIdx"], 7)
        self.assertEqual(result["force"], 12.5)
        self.assertEqual(
            result["crop_roi"],
            {
                "x": 10,
                "y": 20,
                "width": 100,
                "height": 200,
                "source_width": 640,
                "source_height": 480,
            },
        )

    def test_leaves_non_json_descriptions_unchanged(self):
        self.assertEqual(
            add_crop_to_description("microscope frame", (0, 0, 10, 10), (20, 20)),
            "microscope frame",
        )


if __name__ == "__main__":
    unittest.main()
