import json
import unittest

from buti_app.utils.roi import add_crop_to_description, normalized_roi_to_bounds


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
