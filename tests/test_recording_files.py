import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from buti_app.utils.recording_files import (
    find_recording_csv_for_tiff,
    rename_recording_pair,
    validate_path_component,
)


class RecordingFileTests(unittest.TestCase):
    def test_finds_canonical_csv_pair_from_tiff_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            tiff_path = folder / "Trial A_video.tif"
            csv_path = folder / "Trial A_force.csv"
            tiff_path.write_bytes(b"tiff")
            csv_path.write_text("force", encoding="utf-8")

            self.assertEqual(
                find_recording_csv_for_tiff(str(tiff_path)), str(csv_path)
            )

    def test_does_not_guess_when_multiple_unmatched_csv_files_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            tiff_path = folder / "recording.tif"
            tiff_path.write_bytes(b"tiff")
            (folder / "one.csv").write_text("one", encoding="utf-8")
            (folder / "two.csv").write_text("two", encoding="utf-8")

            self.assertIsNone(find_recording_csv_for_tiff(str(tiff_path)))

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
