import csv
import json
import tempfile
import unittest
import sys
from pathlib import Path

try:
    import tifffile
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtGui import QColor, QImage
    app_path = str(Path(__file__).parents[1] / "buti_app")
    sys.path.insert(0, app_path)
    try:
        import recording_manager as recording_manager_module
        from recording_manager import RecordingManager
    finally:
        sys.path.remove(app_path)
except ImportError:  # pragma: no cover - optional recording dependencies
    tifffile = None
    QCoreApplication = None
    QColor = None
    QImage = None
    recording_manager_module = None
    RecordingManager = None


@unittest.skipIf(RecordingManager is None, "Recording dependencies are unavailable")
class RecordingManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_finalizes_transformed_pair_with_unchanged_csv_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            original_minimum = recording_manager_module.MIN_FREE_SPACE_GB
            recording_manager_module.MIN_FREE_SPACE_GB = 0
            try:
                manager = RecordingManager(
                    directory,
                    normalized_roi=(0.25, 0.0, 1.0, 1.0),
                    mirror_horizontal=True,
                )
                finalized = []
                manager.finalized.connect(
                    lambda csv_path, tif_path, summary: finalized.append(
                        (csv_path, tif_path, summary)
                    )
                )
                manager.start_recording()

                image = QImage(4, 2, QImage.Format_Grayscale8)
                for y, row in enumerate(((10, 20, 30, 40), (50, 60, 70, 80))):
                    for x, value in enumerate(row):
                        image.setPixelColor(x, y, QColor(value, value, value))

                manager.append_force(1.25, 7, 0.5, 2, 3.5)
                manager.append_frame(image, None)
                manager._flush_recovery_outputs()
                manager.request_stop()
            finally:
                recording_manager_module.MIN_FREE_SPACE_GB = original_minimum

            self.assertEqual(len(finalized), 1)
            csv_path, tif_path, summary = finalized[0]
            self.assertEqual(summary.status, "passed")
            self.assertEqual(summary.samples_written, 1)
            self.assertEqual(summary.frames_written, 1)
            self.assertFalse(Path(f"{csv_path}.partial").exists())
            self.assertFalse(Path(f"{tif_path}.partial").exists())
            self.assertTrue((Path(directory) / "burst-run.json").exists())
            with open(csv_path, newline="") as csv_file:
                rows = list(csv.reader(csv_file))
            self.assertEqual(
                rows[0], ["time_s", "frame_index", "distance", "cycle", "force"]
            )
            self.assertEqual(rows[1], ["1.25", "7", "0.5", "2", "3.5"])

            with tifffile.TiffFile(tif_path) as tif:
                frame = tif.pages[0].asarray()
                metadata = json.loads(tif.pages[0].description)
            self.assertEqual(frame.shape, (2, 3))
            self.assertEqual(frame[0].tolist(), [40, 30, 20])
            self.assertTrue(metadata["frame_transform"]["mirror_horizontal"])
            self.assertEqual(
                metadata["frame_transform"]["crop_roi"]["source_width"], 4
            )


if __name__ == "__main__":
    unittest.main()
