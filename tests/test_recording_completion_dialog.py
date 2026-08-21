import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP_PATH = str(Path(__file__).parents[1] / "buti_app")

try:
    from PyQt5.QtWidgets import QApplication, QLabel

    sys.path.insert(0, APP_PATH)
    try:
        from ui.recording_completion_dialog import RecordingCompletionDialog
        from utils.recording_summary import RecordingSummary
    finally:
        sys.path.remove(APP_PATH)
except ImportError:  # pragma: no cover - optional UI dependency
    QApplication = None
    QLabel = None
    RecordingCompletionDialog = None
    RecordingSummary = None


@unittest.skipIf(QApplication is None, "PyQt5 UI dependencies are unavailable")
class RecordingCompletionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_integrity_summary_and_braid_action_share_the_completion_window(self):
        summary = RecordingSummary(
            status="passed",
            samples_written=1248,
            frames_written=1248,
            duration_s=62.34,
            csv_size_bytes=18_432,
            tiff_size_bytes=52_428_800,
        )
        dialog = RecordingCompletionDialog(
            "specimen_04",
            "Run7",
            summary=summary,
            braid_application="/Applications/BRAID.app",
        )

        labels = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertTrue(any("Capture checks passed" in text for text in labels))
        self.assertTrue(any("1,248" in text for text in labels))
        self.assertEqual(dialog.braid_button.text(), "Open in BRAID")
        self.assertIn("TIFF", dialog.braid_button.toolTip())
        dialog.close()

    def test_braid_action_is_hidden_when_braid_is_unavailable(self):
        dialog = RecordingCompletionDialog("specimen_04", "Run7")

        self.assertIsNone(dialog.braid_button)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
