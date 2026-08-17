import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtGui import QImage
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication

    app_path = str(Path(__file__).parents[1] / "buti_app")
    sys.path.insert(0, app_path)
    try:
        from ui.canvas.qtcamera_widget import QtCameraWidget
    finally:
        sys.path.remove(app_path)
except ImportError:  # pragma: no cover - optional GUI test dependency
    QApplication = None
    QImage = None
    QtCameraWidget = None


@unittest.skipIf(QtCameraWidget is None, "PyQt5 camera dependencies are unavailable")
class LiveCameraRoiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mirrored_letterboxed_selection_maps_to_source_and_crops_preview(self):
        widget = QtCameraWidget()
        widget.resize(400, 400)
        widget.show()
        image = QImage(200, 100, QImage.Format_Grayscale8)
        image.fill(0)
        widget._on_frame_ready(image, None)
        widget.set_mirroring(True, False)
        self.assertTrue(widget.begin_roi_edit())
        self.app.processEvents()

        # Full frame is displayed at x=0..400, y=100..300. Select display
        # x=10%..50%, y=10%..90%; horizontal mirroring maps it to source
        # x=50%..90%.
        QTest.mousePress(widget, Qt.LeftButton, pos=QPoint(40, 120))
        QTest.mouseMove(widget, QPoint(200, 280))
        QTest.mouseRelease(widget, Qt.LeftButton, pos=QPoint(200, 280))

        left, top, right, bottom = widget.normalized_roi()
        self.assertAlmostEqual(left, 0.5, places=2)
        self.assertAlmostEqual(right, 0.9, places=2)
        self.assertAlmostEqual(top, 0.1, places=2)
        self.assertAlmostEqual(bottom, 0.9, places=2)
        preview = widget._display_qimage()
        self.assertEqual((preview.width(), preview.height()), (80, 80))
        widget.close()


if __name__ == "__main__":
    unittest.main()
