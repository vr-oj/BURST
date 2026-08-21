import tempfile
import unittest
import sys
from pathlib import Path

app_path = str(Path(__file__).parents[1] / "buti_app")
sys.path.insert(0, app_path)
try:
    from utils.recording_folders import (
        is_recording_folder_name,
        next_run_folder_name,
    )
finally:
    sys.path.remove(app_path)

try:
    sys.path.insert(0, app_path)
    try:
        from utils import path_helpers
    finally:
        sys.path.remove(app_path)
except ImportError:  # pragma: no cover - PyQt5 config dependency is optional here
    path_helpers = None


class RunFolderNamingTests(unittest.TestCase):
    def test_next_run_reserves_numbers_used_by_legacy_fill_folders(self):
        self.assertEqual(
            next_run_folder_name(["Fill1", "Run2", "notes"]),
            "Run3",
        )

    def test_current_and_legacy_numbered_folders_are_recognized(self):
        self.assertTrue(is_recording_folder_name("Run12"))
        self.assertTrue(is_recording_folder_name("Fill4"))
        self.assertFalse(is_recording_folder_name("Run notes"))


@unittest.skipIf(path_helpers is None, "PyQt5 configuration dependencies are unavailable")
class SessionPathTests(unittest.TestCase):
    def test_groups_incrementing_runs_under_a_daily_session(self):
        with tempfile.TemporaryDirectory() as directory:
            original_root = path_helpers.config.BURST_ROOT
            try:
                path_helpers.config.BURST_ROOT = directory
                first = Path(path_helpers.get_next_run_folder("Experiment A"))
                second = Path(path_helpers.get_next_run_folder("Experiment A"))
            finally:
                path_helpers.config.BURST_ROOT = original_root

            self.assertEqual(first.name, "Run1")
            self.assertEqual(second.name, "Run2")
            self.assertEqual(first.parent.name, "Experiment A")
            self.assertEqual(first.parent.parent.parent, Path(directory))

    def test_legacy_fill_number_is_not_reused_for_a_new_run(self):
        with tempfile.TemporaryDirectory() as directory:
            original_root = path_helpers.config.BURST_ROOT
            try:
                path_helpers.config.BURST_ROOT = directory
                session = Path(path_helpers.get_date_folder()) / "Experiment A"
                (session / "Fill1").mkdir(parents=True)
                run = Path(path_helpers.get_next_run_folder("Experiment A"))
            finally:
                path_helpers.config.BURST_ROOT = original_root

            self.assertEqual(run.name, "Run2")


if __name__ == "__main__":
    unittest.main()
