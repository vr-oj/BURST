import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication, QComboBox

    app_path = str(Path(__file__).parents[1] / "buti_app")
    sys.path.insert(0, app_path)
    try:
        from main_window import MainWindow
        from ui.control_panels.camera_control_panel import CameraControlPanel
        from ui.control_panels.camera_info_panel import CameraInfoPanel
        from ui.control_panels.plot_control_panel import PlotControlPanel
        from ui.control_panels.top_control_panel import TopControlPanel
    finally:
        sys.path.remove(app_path)
except ImportError:
    QApplication = None
    QComboBox = None
    MainWindow = None
    CameraControlPanel = None
    CameraInfoPanel = None
    PlotControlPanel = None
    TopControlPanel = None


@unittest.skipIf(QApplication is None, "PyQt5 UI dependencies are unavailable")
class MainCardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_camera_metrics_are_compact_and_controls_share_one_card(self):
        camera = CameraInfoPanel()
        controls = CameraControlPanel(embedded=True)
        camera.set_control_panel(controls)
        camera.set_resolution("2448×2048")
        camera.set_fps(10.0)
        camera.set_frame_count(821)

        self.assertFalse(hasattr(camera, "fps_card"))
        self.assertIn("2448×2048", camera.stream_details.text())
        self.assertIn("10.0 fps", camera.stream_details.text())
        self.assertIn("Frame 821", camera.stream_details.text())
        self.assertIs(camera._embedded_control_panel, controls)
        self.assertFalse(camera.advanced_controls.isHidden())
        self.assertFalse(hasattr(camera, "device_combo"))
        camera.close()

    def test_local_camera_and_plot_settings_are_visible(self):
        camera = CameraInfoPanel()
        plot = PlotControlPanel()

        self.assertFalse(camera.advanced_controls.isHidden())
        self.assertFalse(plot.advanced_controls.isHidden())

        camera.close()
        plot.close()

    def test_plot_controls_use_balanced_axis_cards(self):
        plot = PlotControlPanel()

        self.assertEqual(plot.x_axis_card.property("cssClass"), "subCard")
        self.assertEqual(plot.y_axis_card.property("cssClass"), "subCard")
        self.assertEqual(plot.x_min.suffix(), " s")
        self.assertEqual(plot.y_min.suffix(), " mN")
        self.assertFalse(plot.x_min.isEnabled())
        self.assertTrue(plot.y_min.isEnabled())
        self.assertIn("X AUTO", plot.auto_summary_label.text())
        self.assertIn("Y MANUAL", plot.auto_summary_label.text())

        plot.auto_y_cb.setChecked(True)
        self.assertFalse(plot.y_min.isEnabled())
        self.assertIn("Y AUTO", plot.auto_summary_label.text())
        plot.close()

    def test_camera_selector_popup_fits_long_entries(self):
        combo = QComboBox()
        combo.setMinimumWidth(205)
        combo.addItem("Choose camera…")
        combo.addItem("DMK 37BUX250  (S/N: 21420300) — extended device name")

        MainWindow._fit_combo_popup(combo)

        self.assertGreater(combo.view().minimumWidth(), combo.minimumWidth())
        self.assertLessEqual(combo.view().minimumWidth(), 620)
        combo.close()

    def test_workspace_control_cards_are_equalized(self):
        camera = CameraInfoPanel()
        camera.set_control_panel(CameraControlPanel(embedded=True))
        plot = PlotControlPanel()

        class SplitterHarness:
            sizes = None

            @staticmethod
            def width():
                return 1000

            @staticmethod
            def handleWidth():
                return 6

            def setSizes(self, sizes):
                self.sizes = sizes

        class WindowHarness:
            camera_info_panel = camera
            plot_control_panel = plot
            workspace_splitter = SplitterHarness()

        harness = WindowHarness()
        MainWindow._equalize_workspace_panels(harness)

        self.assertEqual(camera.minimumHeight(), plot.minimumHeight())
        self.assertEqual(camera.maximumHeight(), plot.maximumHeight())
        self.assertLessEqual(
            abs(
                harness.workspace_splitter.sizes[0]
                - harness.workspace_splitter.sizes[1]
            ),
            1,
        )

        camera.close()
        plot.close()

    def test_buti_time_uses_minutes_seconds_hundredths_and_minute_unit(self):
        panel = TopControlPanel()
        panel.update_burst_data(62.34, 1, 2.0, 3, 4.0)
        time_html = panel.time_card.value_label.text()
        self.assertIn("01:02.34", time_html)
        self.assertIn("min", time_html)
        self.assertTrue(panel.details_widget.isHidden())
        self.assertLessEqual(panel.sizeHint().height(), 100)
        panel.set_details_expanded(True)
        self.assertFalse(panel.details_widget.isHidden())
        panel.close()

    def test_prominent_record_button_tracks_acquisition_state(self):
        panel = TopControlPanel()
        requests = []
        panel.record_requested.connect(lambda: requests.append("record"))

        panel.set_recording_state("idle", True)
        self.assertIn("Start Recording", panel.record_btn.text())
        self.assertEqual(panel.record_btn.property("recordState"), "idle")
        panel.record_btn.click()
        self.assertEqual(requests, ["record"])

        panel.set_recording_state("recording", True)
        self.assertIn("Stop Recording", panel.record_btn.text())
        self.assertEqual(panel.record_btn.property("recordState"), "recording")

        panel.set_recording_state("finalizing", False)
        self.assertIn("Finalizing", panel.record_btn.text())
        self.assertFalse(panel.record_btn.isEnabled())
        panel.close()

    def test_recording_completion_prompts_rename_before_open_folder(self):
        calls = []

        class CompletionHarness:
            def _prompt_rename_recording_pair(self):
                calls.append("rename")

            def _maybe_prompt_open_folder(self):
                calls.append("folder")

        MainWindow._run_recording_completion_prompts(CompletionHarness())
        self.assertEqual(calls, ["rename", "folder"])


if __name__ == "__main__":
    unittest.main()
