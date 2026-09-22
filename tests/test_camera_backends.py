import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras import CameraDeviceInfo, CameraRegistry
from cameras.controls import CameraControl, CameraController, IC4Controls
from cameras.ic4_backend import IC4Backend
from cameras.opencv_backend import OpenCVBackend, open_capture
from threads.sdk_camera_thread import SDKCameraThread
from threads.micromanager_camera_thread import DevCameraThread
from ui.control_panels.camera_control_panel import CameraControlPanel
from PyQt5.QtWidgets import QApplication
sys.path.pop(0)


class CameraBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_and_broken_sdks_are_optional(self):
        for failure in (ImportError("not installed"), OSError("missing DLL"), RuntimeError("ABI mismatch")):
            registry = CameraRegistry(importer=Mock(side_effect=failure))
            self.assertEqual(registry.discover_cameras(), [])
            self.assertEqual(set(registry.unavailable), {b.key for b in registry.backend_types})

    def test_unified_discovery_and_backend_failure_isolation(self):
        sdk = NS(Library=Mock(), LogLevel=NS(INFO=1), LogTarget=NS(STDERR=1),
                 DeviceEnum=NS(devices=lambda: [NS(model_name="DMK", serial="123", unique_name="usb-id")]))
        generic = CameraDeviceInfo("opencv", "0", "USB #0", native_info=NS(index=0))
        registry = CameraRegistry(importer=Mock(side_effect=ImportError))
        registry.backends = {"ic4": IC4Backend(sdk), "broken": Mock(discover=Mock(side_effect=RuntimeError)),
                             "opencv": Mock(discover=lambda: [generic])}
        devices = registry.discover_cameras()
        self.assertEqual([d.backend for d in devices], ["ic4", "opencv"])
        self.assertEqual((devices[0].id, devices[0].serial), ("usb-id", "123"))
        self.assertIn("IC4", devices[0].display_name)
        registry.close()
        sdk.Library.shutdown.assert_called_once()

    def test_thread_routing(self):
        from threads import sdk_camera_thread
        with patch.object(sdk_camera_thread, "ic4", Mock()):
            thread = IC4Backend(Mock()).create_thread(CameraDeviceInfo("ic4", "a", "A", native_info="native"))
        self.assertIsInstance(thread, SDKCameraThread)
        self.assertEqual(thread._device_info, "native")
        self.assertIsInstance(OpenCVBackend(Mock()).create_thread(
            CameraDeviceInfo("opencv", "0", "USB", native_info={"index": 0})), DevCameraThread)

    def test_opencv_fallback_releases_failed_handles_and_discovery_is_bounded(self):
        bad, good = Mock(), Mock()
        bad.isOpened.return_value = False
        good.isOpened.return_value = True
        cv = Mock(CAP_DSHOW=1, CAP_MSMF=2)
        cv.VideoCapture.side_effect = [bad, good]
        with patch("cameras.opencv_backend.sys.platform", "win32"):
            self.assertIs(open_capture(cv, 0), good)
        bad.release.assert_called_once()
        with patch.dict(os.environ, {}, clear=True), patch("cameras.opencv_backend.open_capture", return_value=good) as opened:
            devices = OpenCVBackend(cv).discover()
        self.assertEqual([d.id for d in devices], ["0", "1", "2"])
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(good.release.call_count, 3)

    def test_commands_use_worker_and_ui_handles_missing_capabilities(self):
        adapter = Mock()
        adapter.read_controls.return_value = {"exposure": CameraControl(10000, 100, 100000)}
        controller = CameraController()
        controller.open(adapter)
        panel = CameraControlPanel()
        panel.set_controller(controller)
        self.assertTrue(panel.exposure_spin.isEnabled())
        self.assertEqual(panel.exposure_spin.value(), 10)
        self.assertFalse(panel.gain_spin.isEnabled())
        self.assertFalse(panel.ae_checkbox.isEnabled())
        adapter.set_value.assert_not_called()  # Initialization must not write camera values.
        panel.exposure_spin.setValue(20)
        adapter.set_value.assert_not_called()
        controller.service(adapter)
        adapter.set_value.assert_called_once_with("exposure", 20000)
        panel.set_recording_state(True)
        self.assertFalse(panel.exposure_spin.isEnabled())
        controller.close()
        panel.set_controller(None)
        self.assertFalse(panel.exposure_spin.isEnabled())
        panel.close()

    def test_ic4_missing_increment_does_not_hide_exposure(self):
        class FloatNode:
            value, minimum, maximum = 1000, 100, 100000
            is_locked, is_readonly = False, False
            @property
            def increment(self):
                raise RuntimeError("continuous property")
        props = Mock()
        props.find_float.return_value = FloatNode()
        props.find_enumeration.side_effect = RuntimeError("missing")
        adapter = IC4Controls(NS(device_property_map=props))
        self.assertEqual(adapter.read_controls()["exposure"].increment, 0)


if __name__ == "__main__":
    unittest.main()
