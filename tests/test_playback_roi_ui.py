import os
import sys
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtCore import QPointF, Qt
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QGraphicsView
    import numpy as np
    from tifffile import TiffFile, TiffWriter

    app_path = str(Path(__file__).parents[1] / "buti_app")
    sys.path.insert(0, app_path)
    try:
        from playback_window import (
            BatchRoiStackExporter,
            GraphicsImageView,
            PlaybackWindow,
            TiffFrameSequence,
        )
    finally:
        sys.path.remove(app_path)
except ImportError:
    GraphicsImageView = None
    PlaybackWindow = None
    TiffFrameSequence = None
    BatchRoiStackExporter = None


class PlaybackWindowWithoutFilePicker(PlaybackWindow if PlaybackWindow else object):
    def pick_files(self):
        pass


@unittest.skipIf(GraphicsImageView is None, "PyQt5 playback dependencies are unavailable")
class RoiDrawingInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_roi_mode_uses_crosshair_and_finishes_after_drag(self):
        view = GraphicsImageView()
        view.resize(240, 240)
        pixmap = QPixmap(200, 200)
        pixmap.fill(Qt.black)
        view.set_pixmap(pixmap)
        view.show()
        self.app.processEvents()

        finished = []
        view.roi_finished.connect(lambda: finished.append(True))
        view.enable_roi(True)

        self.assertEqual(view.dragMode(), QGraphicsView.NoDrag)
        self.assertEqual(view.viewport().cursor().shape(), Qt.CrossCursor)

        start = view.mapFromScene(QPointF(25, 30))
        end = view.mapFromScene(QPointF(150, 160))
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), pos=end)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)
        self.app.processEvents()

        self.assertEqual(finished, [True])
        self.assertIsNotNone(view.get_normalized_roi())

        view.enable_roi(False)
        self.assertEqual(view.dragMode(), QGraphicsView.ScrollHandDrag)
        self.assertNotEqual(view.viewport().cursor().shape(), Qt.CrossCursor)
        view.close()

    def test_button_and_status_show_roi_mode_and_completion(self):
        window = PlaybackWindowWithoutFilePicker()
        window.show()
        self.app.processEvents()

        window.frames = [type("Frame", (), {"shape": (200, 200)})()]
        pixmap = QPixmap(200, 200)
        pixmap.fill(Qt.black)
        window.view.set_pixmap(pixmap)
        window._refresh_roi_controls()
        self.app.processEvents()

        window.roi_btn.click()
        self.assertTrue(window.roi_btn.isChecked())
        self.assertEqual(window.roi_btn.text(), "Cancel ROI")
        self.assertEqual(window.view.viewport().cursor().shape(), Qt.CrossCursor)
        self.assertIn("drag over the image", window.statusBar().currentMessage())

        start = window.view.mapFromScene(QPointF(25, 30))
        end = window.view.mapFromScene(QPointF(150, 160))
        QTest.mousePress(window.view.viewport(), Qt.LeftButton, pos=start)
        QTest.mouseMove(window.view.viewport(), pos=end)
        QTest.mouseRelease(window.view.viewport(), Qt.LeftButton, pos=end)
        self.app.processEvents()

        self.assertFalse(window.roi_btn.isChecked())
        self.assertEqual(window.roi_btn.text(), "Draw ROI")
        self.assertNotEqual(window.view.viewport().cursor().shape(), Qt.CrossCursor)
        self.assertTrue(window.export_roi_stack_btn.isEnabled())
        self.assertIn("ROI selected:", window.statusBar().currentMessage())
        window.close()

    def test_manual_pixel_roi_is_exact_and_reusable(self):
        window = PlaybackWindowWithoutFilePicker()
        window.frames = [type("Frame", (), {"shape": (200, 300)})()]
        pixmap = QPixmap(300, 200)
        pixmap.fill(Qt.black)
        window.view.set_pixmap(pixmap)
        window._configure_roi_fields((200, 300))

        window.roi_x_spin.setValue(25)
        window.roi_y_spin.setValue(30)
        window.roi_width_spin.setValue(120)
        window.roi_height_spin.setValue(80)
        window.apply_manual_roi()
        self.app.processEvents()

        self.assertEqual(window._roi_frame_bounds(), (25, 30, 145, 110))
        self.assertTrue(window.batch_export_roi_stack_btn.isEnabled())
        self.assertFalse(hasattr(window, "zoom_roi_btn"))

        window.clear_roi()
        self.assertIsNone(window._roi_frame_bounds())
        self.assertEqual(window.roi_width_spin.value(), 120)
        self.assertEqual(window.roi_height_spin.value(), 80)
        window.close()

    def test_tiff_frames_are_loaded_lazily_with_a_bounded_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large_stack.tif"
            with TiffWriter(path) as writer:
                for value in range(6):
                    writer.write(
                        np.full((20, 30), value, dtype=np.uint8),
                        photometric="minisblack",
                    )

            frames = TiffFrameSequence(path, 6, cache_size=2, cache_bytes=2000)
            self.assertEqual(len(frames), 6)
            self.assertEqual(int(frames[0][0, 0]), 0)
            self.assertEqual(int(frames[3][0, 0]), 3)
            self.assertEqual(int(frames[5][0, 0]), 5)
            self.assertLessEqual(len(frames._cache), 2)
            self.assertLessEqual(frames._cached_bytes, 2000)
            frames.clear()

    def test_batch_worker_applies_identical_pixel_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = []
            outputs = []
            for run_number in (1, 2):
                source = Path(tmp) / f"run{run_number}.tif"
                output = Path(tmp) / f"run{run_number}_cropped.tif"
                with TiffWriter(source) as writer:
                    for frame_number in range(3):
                        writer.write(
                            np.arange(80, dtype=np.uint8).reshape(8, 10)
                            + frame_number,
                            photometric="minisblack",
                        )
                jobs.append((str(source), str(output), (8, 10)))
                outputs.append(output)

            results = []
            worker = BatchRoiStackExporter(jobs, (2, 1, 7, 6))
            worker.finished.connect(
                lambda completed, failures: results.append((completed, failures))
            )
            worker.run()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0][1], [])
            self.assertEqual(len(results[0][0]), 2)
            for output in outputs:
                with TiffFile(output) as cropped:
                    self.assertEqual(tuple(cropped.pages[0].shape), (5, 5))


if __name__ == "__main__":
    unittest.main()
