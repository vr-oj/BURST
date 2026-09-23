import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PyQt5.QtCore import QThread, pyqtSignal
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
                   CameraDeviceInfo("spinnaker", "2", "Blackfly — Spinnaker")]
        registry = Mock()
        registry.discover_cameras.return_value = devices
        registry.list_modes.return_value = [CameraMode(4, 2, "Mono8")]
        registry.get_thread.side_effect = lambda device, parent=None: CameraThread(parent)
        with patch.object(main_window, "CameraRegistry", return_value=registry):
            window = main_window.MainWindow()
        try:
            self.assertEqual(window.device_combo.count(), 3)
            window.device_combo.setCurrentIndex(2)
            registry.list_modes.assert_called_with(devices[1])
            window._on_start_stop_camera()
            thread = window.camera_thread
            self.wait_for(lambda: window._last_camera_frame_monotonic is not None)
            registry.get_thread.assert_called_with(devices[1], parent=window)
            self.assertFalse(window.device_combo.isEnabled())
            self.assertEqual(thread.resolution, (4, 2, "Mono8"))
            # A running camera with one recent image must not bypass the rate check.
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
        finally:
            window.close()
            self.app.processEvents()
        registry.close.assert_called_once()
