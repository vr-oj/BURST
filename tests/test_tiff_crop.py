import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from tifffile import TiffFile, TiffWriter

    from buti_app.utils.tiff_crop import export_cropped_tiff
except ImportError:
    np = None
    TiffFile = None
    TiffWriter = None
    export_cropped_tiff = None


@unittest.skipIf(export_cropped_tiff is None, "NumPy/tifffile are not installed")
class ExportCroppedTiffTests(unittest.TestCase):
    def test_preserves_frames_pixels_dtype_and_burst_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.tif"
            output = Path(tmp) / "cropped.tif"
            frames = [
                np.arange(48, dtype=np.uint16).reshape(6, 8) + index * 100
                for index in range(3)
            ]
            with TiffWriter(source, bigtiff=True) as writer:
                for index, frame in enumerate(frames):
                    writer.write(
                        frame,
                        photometric="minisblack",
                        description=json.dumps(
                            {"frameIdx": index, "force": index + 0.5}
                        ),
                    )

            progress = []
            frame_count = export_cropped_tiff(
                str(source),
                str(output),
                (2, 1, 7, 5),
                (6, 8),
                on_progress=lambda current, total: progress.append((current, total)),
            )

            self.assertEqual(frame_count, 3)
            self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])
            with TiffFile(output) as result:
                self.assertEqual(len(result.pages), 3)
                for index, page in enumerate(result.pages):
                    array = page.asarray()
                    self.assertEqual(array.shape, (4, 5))
                    self.assertEqual(array.dtype, np.dtype("uint16"))
                    np.testing.assert_array_equal(array, frames[index][1:5, 2:7])

                    metadata = json.loads(page.description)
                    self.assertEqual(metadata["frameIdx"], index)
                    self.assertEqual(metadata["force"], index + 0.5)
                    self.assertEqual(
                        metadata["crop_roi"],
                        {
                            "x": 2,
                            "y": 1,
                            "width": 5,
                            "height": 4,
                            "source_width": 8,
                            "source_height": 6,
                        },
                    )

    def test_cancellation_does_not_replace_an_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.tif"
            output = Path(tmp) / "cropped.tif"
            with TiffWriter(source) as writer:
                writer.write(np.zeros((4, 4), dtype=np.uint8))
            output.write_bytes(b"existing output")

            from buti_app.utils.tiff_crop import CropCanceled

            with self.assertRaises(CropCanceled):
                export_cropped_tiff(
                    str(source),
                    str(output),
                    (0, 0, 2, 2),
                    (4, 4),
                    should_cancel=lambda: True,
                )

            self.assertEqual(output.read_bytes(), b"existing output")

    def test_rejects_the_source_as_the_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.tif"
            with TiffWriter(source) as writer:
                writer.write(np.zeros((4, 4), dtype=np.uint8))

            with self.assertRaisesRegex(ValueError, "cannot replace the source"):
                export_cropped_tiff(
                    str(source),
                    str(source),
                    (0, 0, 2, 2),
                    (4, 4),
                )

            with TiffFile(source) as result:
                self.assertEqual(len(result.pages), 1)
                self.assertEqual(result.pages[0].shape, (4, 4))


if __name__ == "__main__":
    unittest.main()
