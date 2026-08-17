import unittest

try:
    from PyQt5.QtGui import QColor, QImage
    from buti_app.utils.frame_transform import transform_qimage
except ImportError:  # pragma: no cover - optional GUI test dependency
    QColor = None
    QImage = None
    transform_qimage = None


@unittest.skipIf(QImage is None, "PyQt5 is unavailable")
class FrameTransformTests(unittest.TestCase):
    def _source(self):
        image = QImage(4, 2, QImage.Format_Grayscale8)
        values = ((10, 20, 30, 40), (50, 60, 70, 80))
        for y, row in enumerate(values):
            for x, value in enumerate(row):
                image.setPixelColor(x, y, QColor(value, value, value))
        return image

    def test_crops_native_pixels_then_mirrors(self):
        transformed, metadata = transform_qimage(
            self._source(),
            (0.25, 0.0, 1.0, 1.0),
            mirror_horizontal=True,
        )
        self.assertEqual((transformed.width(), transformed.height()), (3, 2))
        self.assertEqual(
            [transformed.pixelColor(x, 0).red() for x in range(3)],
            [40, 30, 20],
        )
        self.assertEqual(metadata["crop_roi"]["source_width"], 4)
        self.assertTrue(metadata["mirror_horizontal"])


if __name__ == "__main__":
    unittest.main()
