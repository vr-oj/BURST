import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from buti_app.utils.recording_files import (
    rename_recording_pair,
    validate_path_component,
)


class RecordingFileTests(unittest.TestCase):
    def test_validates_windows_safe_components(self):
        self.assertEqual(validate_path_component("  Trial 7  "), "Trial 7")
        for invalid in ("", "../trial", "bad:name", "CON", "name."):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_path_component(invalid)

    def test_renames_csv_and_tiff_as_one_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            csv_path = folder / "recording_force.csv"
            tiff_path = folder / "recording_video.tif"
            csv_path.write_text("csv", encoding="utf-8")
            tiff_path.write_bytes(b"tiff")

            renamed_csv, renamed_tiff = rename_recording_pair(
                str(csv_path), str(tiff_path), "Sample A"
            )

            self.assertEqual(Path(renamed_csv).name, "Sample A_force.csv")
            self.assertEqual(Path(renamed_tiff).name, "Sample A_video.tif")
            self.assertEqual(Path(renamed_csv).read_text(encoding="utf-8"), "csv")
            self.assertEqual(Path(renamed_tiff).read_bytes(), b"tiff")
            self.assertFalse(csv_path.exists())
            self.assertFalse(tiff_path.exists())

    def test_never_overwrites_an_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            csv_path = folder / "old_force.csv"
            tiff_path = folder / "old_video.tif"
            csv_path.write_text("old csv", encoding="utf-8")
            tiff_path.write_bytes(b"old tiff")
            (folder / "new_force.csv").write_text("keep", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                rename_recording_pair(str(csv_path), str(tiff_path), "new")

            self.assertTrue(csv_path.exists())
            self.assertTrue(tiff_path.exists())
            self.assertEqual(
                (folder / "new_force.csv").read_text(encoding="utf-8"), "keep"
            )

    def test_rolls_csv_back_if_tiff_rename_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            csv_path = folder / "old_force.csv"
            tiff_path = folder / "old_video.tif"
            csv_path.write_text("csv", encoding="utf-8")
            tiff_path.write_bytes(b"tiff")
            real_rename = Path.rename

            def fail_tiff(source, target):
                if source.name == "old_video.tif":
                    raise OSError("simulated TIFF rename failure")
                return real_rename(source, target)

            with patch.object(Path, "rename", fail_tiff):
                with self.assertRaises(OSError):
                    rename_recording_pair(str(csv_path), str(tiff_path), "new")

            self.assertTrue(csv_path.exists())
            self.assertTrue(tiff_path.exists())
            self.assertFalse((folder / "new_force.csv").exists())


if __name__ == "__main__":
    unittest.main()
