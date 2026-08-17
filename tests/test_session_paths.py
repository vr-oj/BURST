import tempfile
import unittest
import sys
from pathlib import Path

try:
    app_path = str(Path(__file__).parents[1] / "buti_app")
    sys.path.insert(0, app_path)
    try:
        from utils import path_helpers
    finally:
        sys.path.remove(app_path)
except ImportError:  # pragma: no cover - PyQt5 config dependency is optional here
    path_helpers = None


@unittest.skipIf(path_helpers is None, "PyQt5 configuration dependencies are unavailable")
class SessionPathTests(unittest.TestCase):
    def test_groups_incrementing_fills_under_a_daily_session(self):
        with tempfile.TemporaryDirectory() as directory:
            original_root = path_helpers.config.BURST_ROOT
            try:
                path_helpers.config.BURST_ROOT = directory
                first = Path(path_helpers.get_next_fill_folder("Experiment A"))
                second = Path(path_helpers.get_next_fill_folder("Experiment A"))
            finally:
                path_helpers.config.BURST_ROOT = original_root

            self.assertEqual(first.name, "Fill1")
            self.assertEqual(second.name, "Fill2")
            self.assertEqual(first.parent.name, "Experiment A")
            self.assertEqual(first.parent.parent.parent, Path(directory))


if __name__ == "__main__":
    unittest.main()
