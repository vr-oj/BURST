"""Recording boundaries tested without opening a camera or a serial port."""
import os
import sys
import tempfile
import time
import unittest
import json
import numpy as np
import tifffile
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
import main_window
from cameras import CameraDeviceInfo, CameraMode
from cameras.controls import CameraController, EmptyControls
from cameras.frame_data import FrameData
from cameras.timing_thread import TimingCameraThread
from cameras.trigger import AUTO_TRIGGER, choose_trigger_source, configure_external_trigger
from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication
sys.path.pop(0)


class PreviewCamera(TimingCameraThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.controller = CameraController()
        self.stopping = False
        self.allow_arm = Event()
        self.fail_arm = False
        self.switches = []

    def set_resolution(self, resolution):
        pass

    def stop(self):
        self.stopping = True
        self.allow_arm.set()

    def run(self):
        self.controller.open(EmptyControls())
        self.grabber_ready.emit()
        image = QImage(4, 2, QImage.Format_Grayscale8)
        image.fill(40)
        self.frame_ready.emit(image, None)

        def switch(source):
            if source:
                self.allow_arm.wait(2)
                if self.fail_arm:
                    raise RuntimeError("Trigger readback failed")
            self.switches.append(source)
            return {"TriggerSource": "Line0", "TriggerMode": "On"} if source else {}

        try:
            while not self.stopping:
                self.service_timing(switch)
                self.msleep(5)
        except Exception as exc:
            self.error.emit(str(exc), "test-timing")
        finally:
            self.controller.close()


class RecordingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QThread.msleep(5)
        self.assertTrue(predicate())

    def window(self, real_recorder=False):
        registry = Mock()
        registry.discover_cameras.return_value = [CameraDeviceInfo("test", "1", "Test camera")]
        registry.list_modes.return_value = [CameraMode(4, 2, "Mono8")]
        registry.get_thread.side_effect = lambda device, parent=None: PreviewCamera(parent)
        with patch.object(main_window, "CameraRegistry", return_value=registry), \
                patch.object(main_window, "load_app_setting", side_effect=lambda key, default=None: default):
            window = main_window.MainWindow()
        self.addCleanup(window.close)
        window.device_combo.setCurrentIndex(1)
        window._on_start_stop_camera()
        self.wait_for(lambda: window._last_camera_frame_monotonic is not None)
        window._current_session_name = "test"
        window._run_silent_recording_preflight = Mock(return_value=True)
        if not real_recorder:
            window._start_recording_files = Mock()
        window._show_error_dialog = Mock()
        return window

    def test_full_recording_pairs_both_orders_and_returns_to_preview(self):
        class SerialStub(QThread):
            data_ready = pyqtSignal(float, int, float, int, float)
            def isRunning(self):
                return True
            def send_command(self, command):
                commands.append(command)
                return True
            def stop(self):
                pass
        commands = []
        window = self.window(real_recorder=True)
        serial = SerialStub()
        window._serial_thread = serial
        window._run_recording_completion_prompts = Mock()
        camera = window.camera_thread
        camera.allow_arm.set()
        image = QImage(4, 2, QImage.Format_Grayscale8)
        image.fill(1)
        try:
            with tempfile.TemporaryDirectory() as directory, \
                    patch.object(main_window, "get_next_run_folder", return_value=directory), \
                    patch("recording_manager.MIN_FREE_SPACE_GB", 0):
                window._on_start_recording()
                self.wait_for(lambda: window._recording_state == "recording")
                self.assertEqual(commands, ["G"])
                self.assertEqual(camera.switches, ["auto"])
                camera.frame_ready.emit(image, FrameData.copy(np.ones((2, 4), np.uint8), camera_frame_id=51))
                serial.data_ready.emit(.1, 1, 0, 0, 10)
                serial.data_ready.emit(.2, 2, 0, 0, 20)
                camera.frame_ready.emit(image, FrameData.copy(np.full((2, 4), 2, np.uint8), camera_frame_id=52))
                window._on_stop_recording()
                self.wait_for(lambda: window._recording_state == "idle" and not window._timing_transition)
                self.assertEqual(commands, ["G", "S"])
                self.assertEqual(camera.switches, ["auto", ""])
                self.assertEqual(window._last_recording_summary.status, "passed")
                manifest = json.loads((Path(directory) / "burst-run.json").read_text(encoding="utf-8"))
                self.assertIn('"timing_mode": "external_trigger"', json.dumps(manifest))
                with tifffile.TiffFile(window._last_recording_paths["tiff"]) as stack:
                    self.assertEqual(len(stack.pages), 2)
                    for index, page in enumerate(stack.pages, 1):
                        self.assertEqual(json.loads(page.description)["force"], index * 10)
                        self.assertEqual(page.asarray()[0, 0], index)
        finally:
            if window._recording_state in {"preparing", "recording"}:
                window._on_stop_recording()
            if window._recorder_thread is not None:
                self.wait_for(lambda: window._recorder_thread is None)
            window._serial_thread = None

    def test_preview_then_arm_before_creating_recorder_and_sending_start(self):
        window = self.window()
        camera = window.camera_thread
        self.assertEqual(camera.hardware_trigger_source, "")
        window._on_start_recording()
        self.assertEqual(window._timing_transition, "arming")
        self.assertEqual(window.top_ctrl.record_btn.text(), "Preparing…\nCancel")
        self.assertEqual(window.recording_action.text(), "Cancel Preparation")
        self.assertFalse(window.top_ctrl.start_btn.isEnabled())
        window._start_recording_files.assert_not_called()
        camera.allow_arm.set()
        self.wait_for(lambda: window._start_recording_files.called)
        self.assertTrue(window._camera_armed)
        self.assertEqual(camera.switches, [AUTO_TRIGGER])
        self.assertFalse(window.camera_control_panel.isEnabled())
        # Recorder readiness is the only point that may start the box.
        window._send_serial_command = Mock(return_value=True)
        window._current_run_folder = "test"
        window._on_recorder_ready()
        window._send_serial_command.assert_called_once_with("G")
        self.assertIn("Stop Recording", window.top_ctrl.record_btn.text())
        window._recording_state = "idle"
        window._device_run_active = False
        window._restore_camera_preview()
        self.wait_for(lambda: not window._timing_transition)
        self.assertEqual(camera.switches, [AUTO_TRIGGER, ""])
        self.assertFalse(window._camera_armed)
        self.assertTrue(window.camera_control_panel.isEnabled())
        self.assertIn("Start Recording", window.top_ctrl.record_btn.text())

    def test_failed_arm_does_not_create_files_start_box_or_enable_approximate_mode(self):
        window = self.window()
        camera = window.camera_thread
        camera.fail_arm = True
        window._send_serial_command = Mock()
        window._on_start_recording()
        camera.allow_arm.set()
        self.wait_for(lambda: window.camera_thread is None)
        window._start_recording_files.assert_not_called()
        window._send_serial_command.assert_not_called()
        self.assertEqual(window._recording_state, "idle")
        self.assertEqual(window._hardware_trigger_source, AUTO_TRIGGER)
        self.assertFalse(window.timing_action.isChecked())
        window._show_error_dialog.assert_called_once()

    def test_cancel_during_arming_ignores_late_ready(self):
        window = self.window()
        window._send_serial_command = Mock()
        window._on_start_recording()
        window.top_ctrl.record_btn.click()
        self.wait_for(lambda: window.camera_thread is None)
        window._start_recording_files.assert_not_called()
        window._send_serial_command.assert_not_called()
        self.assertEqual(window._recording_state, "idle")

    def test_unsupported_backend_can_preview_but_requires_explicit_approximate_choice(self):
        window = self.window()
        window.camera_thread.request_timing = None
        with patch.object(main_window.QMessageBox, "information") as notice:
            window._on_start_recording()
        notice.assert_called_once()
        window._start_recording_files.assert_not_called()
        with patch.object(main_window.QMessageBox, "warning", return_value=main_window.QMessageBox.Yes):
            window._configure_timing(True)
        window._on_start_recording()
        window._start_recording_files.assert_called_once()
        self.assertEqual(window._hardware_trigger_source, "")
        window._on_device_selected(1)
        self.assertEqual(window._hardware_trigger_source, AUTO_TRIGGER)

    def test_camera_sources_are_not_guessed(self):
        self.assertEqual(choose_trigger_source("Line1", ("Line0", "Line1", "Software")), "Line1")
        self.assertEqual(choose_trigger_source("Software", ("Software", "Line0")), "Line0")
        for choices in (("Software",), ("Line0", "Line1")):
            with self.assertRaisesRegex(RuntimeError, "one-time setup"):
                choose_trigger_source("Software", choices)
        nodes = {"TriggerSource": "Software"}
        actual = configure_external_trigger(nodes.__getitem__, nodes.__setitem__, AUTO_TRIGGER,
                                            choices=lambda: ("Software", "Line0"))
        self.assertEqual(actual["TriggerSource"], "Line0")

    def test_invalid_ready_cannot_start_arduino(self):
        window = self.window()
        window._recording_state = "preparing"
        window._send_serial_command = Mock()
        window._on_recorder_ready()
        window._send_serial_command.assert_not_called()

    def test_fixed_trigger_nodes_are_accepted_only_when_they_already_match(self):
        nodes = {"TriggerMode": "Off", "TriggerSelector": "FrameStart",
                 "TriggerSource": "Line0", "TriggerActivation": "RisingEdge"}
        def write(name, value):
            if name != "TriggerMode":
                raise RuntimeError("read-only node")
            nodes[name] = value
        configured = configure_external_trigger(nodes.__getitem__, write, "auto", choices=lambda: ("Line0",))
        self.assertEqual(configured["TriggerMode"], "On")
        nodes["TriggerActivation"] = "FallingEdge"
        with self.assertRaisesRegex(RuntimeError, "read-only"):
            configure_external_trigger(nodes.__getitem__, write, "auto", choices=lambda: ("Line0",))
        self.assertEqual(nodes["TriggerMode"], "Off")
