import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtTest import QTest
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
import main_window
from cameras import CameraDeviceInfo, CameraMode
from cameras.controls import CameraController, EmptyControls
sys.path.pop(0)


class CameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.controller = CameraController()
        self.stopping = False

    def set_resolution(self, resolution):
        self.resolution = resolution

    def run(self):
        self.controller.open(EmptyControls())
        self.grabber_ready.emit()
        image = QImage(4, 2, QImage.Format_Grayscale8)
        image.fill(50)
        self.frame_ready.emit(image, {"backend": "test"})
        while not self.stopping:
            self.msleep(5)
        self.controller.close()

    def stop(self):
        self.stopping = True


class CameraLifecycleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QThread.msleep(5)
        self.assertTrue(predicate())

    def test_mixed_selector_routes_modes_and_preserves_thread_until_finished(self):
        devices = [CameraDeviceInfo("ic4", "1", "DMK — IC4"),
                   CameraDeviceInfo("micromanager", "2", "Camera — Micro-Manager")]
        registry = Mock()
        registry.discover_cameras.return_value = devices
        registry.list_modes.return_value = [CameraMode(4, 2, "Mono8")]
        registry.get_thread.side_effect = lambda device, parent=None: CameraThread(parent)
        with patch.object(main_window, "CameraRegistry", return_value=registry):
            window = main_window.MainWindow()
        try:
            self.assertEqual(window.device_combo.count(), 5)
            setup_index = window.device_combo.count() - 1
            self.assertEqual(window.device_combo.itemText(setup_index), "Micro-Manager Camera Setup…")
            window.device_combo.setCurrentIndex(2)
            registry.list_modes.assert_called_with(devices[1])
            window._hardware_trigger_source = ""
            window.timing_action.setChecked(True)
            resolution = window.resolution_combo.currentData()
            mode_reads = registry.list_modes.call_count
            with patch.object(window, "_setup_micro_manager") as setup, \
                    patch.object(window.camera_widget, "clear_roi") as clear_roi:
                window.device_combo.showPopup()
                popup = window.device_combo.view()
                popup.setCurrentIndex(popup.model().index(setup_index, 0))
                QTest.keyClick(popup, Qt.Key_Return)
                self.app.processEvents()
                setup.assert_called_once_with()
                clear_roi.assert_not_called()
            self.assertEqual(window.device_combo.currentData(), devices[1])
            self.assertEqual(window.resolution_combo.currentData(), resolution)
            self.assertEqual(registry.list_modes.call_count, mode_reads)
            self.assertEqual(window._hardware_trigger_source, "")
            self.assertTrue(window.timing_action.isChecked())
            window._on_start_stop_camera()
            thread = window.camera_thread
            self.wait_for(lambda: window._last_camera_frame_monotonic is not None)
            registry.get_thread.assert_called_with(devices[1], parent=window)
            self.assertFalse(window.device_combo.isEnabled())
            self.assertEqual(thread.resolution, (4, 2, "Mono8"))
            # A running camera with one recent image must not bypass the rate check.
            window._hardware_trigger_source = ""  # Explicit approximate recording.
            with tempfile.TemporaryDirectory() as directory, \
                    patch.object(main_window.config, "BURST_ROOT", directory), \
                    patch.object(window, "_show_camera_rate_help") as help_dialog:
                self.assertFalse(window._run_silent_recording_preflight())
                self.assertIn("Camera rate", help_dialog.call_args.args[0])
            window._populate_device_list()
            registry.discover_cameras.assert_called_once()
            # Finishing a recording must not allow reopening an active camera for mode queries.
            window._on_recorder_thread_finished()
            self.assertFalse(window.device_combo.isEnabled())
            self.assertFalse(window.resolution_combo.isEnabled())
            window._on_start_stop_camera()
            self.assertIs(window.camera_thread, thread)
            self.wait_for(lambda: window.camera_thread is None)
            self.assertTrue(window.device_combo.isEnabled())
            self.assertIsNone(window.camera_control_panel.controller)
            window._populate_device_list()
            self.assertEqual(window.device_combo.currentData().id, "2")
            self.assertEqual(window.device_combo.itemText(window.device_combo.count() - 1),
                             "Micro-Manager Camera Setup…")
        finally:
            window.close()
            self.app.processEvents()
        registry.close.assert_called_once()
