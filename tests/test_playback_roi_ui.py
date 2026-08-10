import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtCore import QPointF, Qt
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QGraphicsView

    app_path = str(Path(__file__).parents[1] / "buti_app")
    sys.path.insert(0, app_path)
    try:
        from playback_window import GraphicsImageView, PlaybackWindow
    finally:
        sys.path.remove(app_path)
except ImportError:
    GraphicsImageView = None
    PlaybackWindow = None


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


if __name__ == "__main__":
    unittest.main()
