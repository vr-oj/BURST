import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras.micro_manager_backend import MicroManagerBackend, MicroManagerSession, MicroManagerControls
from cameras.registry import CameraRegistry
from cameras.controls import CameraController
from cameras.micro_manager_process import MicroManagerService, MicroManagerClient
from threads.mmcore_camera_thread import MMCoreCameraThread, copy_mm_frame
from ui.micro_manager_setup import MicroManagerSetupDialog
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.camera_properties_dialog import CameraPropertiesDialog
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QThread
sys.path.pop(0)


def fake_core():
    core = Mock()
    core.getLoadedDevicesOfType.return_value = ["Camera", "Camera2"]
    core.getCameraDevice.return_value = "Camera"
    core.getVersionInfo.return_value = "MMCore test"
    core.getAPIVersionInfo.return_value = "Device API version 75"
    core.getDeviceLibrary.return_value = "TestAdapter"
    values = {"Exposure": "10", "Gain": "2", "PixelType": "16bit",
              "TriggerMode": "Internal", "Serial": "123", "SetupOnly": "fixed",
              "AcquisitionFrameRate": "10"}
    core.getDevicePropertyNames.side_effect = lambda camera: list(values)
    core.hasProperty.side_effect = lambda camera, key: key in values
    core.getProperty.side_effect = lambda camera, key: values[key]
    core.setProperty.side_effect = lambda camera, key, value: values.__setitem__(key, value)
    core.hasPropertyLimits.side_effect = lambda camera, key: key in {"Exposure", "AcquisitionFrameRate"}
    core.getPropertyLowerLimit.return_value = 1
    core.getPropertyUpperLimit.return_value = 100
    core.isPropertyReadOnly.side_effect = lambda camera, key: key == "Serial"
    core.isPropertyPreInit.side_effect = lambda camera, key: key == "SetupOnly"
    core.getAllowedPropertyValues.side_effect = lambda camera, key: ("Internal", "External") if key == "TriggerMode" else ()
    core.getExposure.side_effect = lambda: float(values["Exposure"])
    core.setExposure.side_effect = lambda value: values.__setitem__("Exposure", str(value))
    core.getROI.return_value = (0, 0, 4, 2)
    core.isBufferOverflowed.return_value = False
    core.getRemainingImageCount.return_value = 1
    core.getNumberOfComponents.return_value = 1
    core.getNumberOfCameraChannels.return_value = 1
    core.getImageWidth.return_value = 4
    core.getImageHeight.return_value = 2
    core.getImageBitDepth.return_value = 12
    core.popNextImage.return_value = np.full((2, 4), 2048, np.uint16)
    return core, NS(CMMCore=lambda: core, CameraDevice=2)


class LocalClient:
    """Exercise RPC operations against a fake SDK without opening real hardware."""
    def __init__(self, sdk, **kwargs):
        self.service = MicroManagerService(sdk)

    def __enter__(self):
        return self

    def request(self, method, *args, **kwargs):
        return self.service.dispatch(method, args)

    def __exit__(self, *args):
        self.service.close()


class MicroManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = Path(self.directory.name) / "camera.cfg"
        config.write_text("# Test configuration", encoding="utf-8")
        self.profile = dict(installation=self.directory.name, config=str(config), camera="Camera")
        self.core, self.sdk = fake_core()
        self.client_patch = patch("ui.micro_manager_setup.MicroManagerClient",
                                  side_effect=lambda **kw: LocalClient(self.sdk))
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    def thread(self, sdk=None):
        return MMCoreCameraThread(profile=self.profile,
            client_factory=lambda **kw: LocalClient(sdk or self.sdk))

    def test_registry_profiles_do_not_open_hardware_on_refresh(self):
        registry = CameraRegistry("micromanager", importer=lambda _: self.sdk, plugin_entries=[])
        registry.set_micro_manager_profiles([self.profile])
        device, = registry.discover_cameras()
        self.assertEqual(device.backend, "micromanager")
        self.assertEqual(registry.list_modes(device)[0].as_tuple(), (0, 0, "Configuration"))
        self.assertIsInstance(registry.get_thread(device), MMCoreCameraThread)
        self.core.loadSystemConfiguration.assert_not_called()

    def test_configured_dimensions_are_shown_without_opening_camera(self):
        backend = MicroManagerBackend(self.sdk)
        backend.profiles = [dict(self.profile, configured_mode={"width": 3072, "height": 2048})]
        device, = backend.discover()
        mode, = backend.list_modes(device)
        self.assertEqual(mode.as_tuple(), (3072, 2048, "Configuration"))
        self.assertIn("3072", mode.display_name)
        self.core.loadSystemConfiguration.assert_not_called()

    def test_missing_configuration_releases_resources(self):
        with self.assertRaisesRegex(ValueError, "existing"):
            with MicroManagerSession(self.sdk, dict(self.profile, config="missing.cfg")):
                pass
        self.core.loadSystemConfiguration.assert_not_called()

    def test_failed_configuration_reports_api_and_unloads_partial_devices(self):
        self.core.loadSystemConfiguration.side_effect = RuntimeError("missing vendor DLL")
        with self.assertRaisesRegex(RuntimeError, "API version 75"):
            with MicroManagerSession(self.sdk, self.profile):
                pass
        self.core.unloadAllDevices.assert_called_once()

    def test_selected_camera_and_trigger_configuration_are_preserved(self):
        with MicroManagerSession(self.sdk, dict(self.profile, camera="Camera2")) as session:
            self.assertEqual(session.camera, "Camera2")
        self.core.setProperty.assert_not_called()
        self.core.setCameraDevice.assert_called_with("Camera2")
        self.core.unloadAllDevices.assert_called_once()

    def test_controls_keep_native_units_and_readonly_properties(self):
        with MicroManagerSession(self.sdk, self.profile) as session:
            adapter = MicroManagerControls(session)
            controls = adapter.read_controls()
            self.assertEqual(controls["exposure"].value, 10000)
            self.assertEqual(controls["fps"].value, 10)
            self.assertNotIn("gain", controls)  # Do not claim unknown gain units are dB.
            self.assertEqual(controls["mm:Gain"].value, "2")
            self.assertFalse(controls["mm:Serial"].writable)
            self.assertFalse(controls["mm:SetupOnly"].writable)
            with self.assertRaises(RuntimeError):
                adapter.set_value("mm:Serial", "456")
            with self.assertRaises(ValueError):
                adapter.set_value("mm:TriggerMode", "Invalid")
            adapter.set_value("exposure", 25000)
            self.assertEqual(adapter.read_controls()["exposure"].value, 25000)
            adapter.set_value("mmcore:Sensor ROI (x,y,width,height)", "0,0,2,2")
            self.core.setROI.assert_called_with(0, 0, 2, 2)
            adapter.set_value("mmcore:Sensor ROI (x,y,width,height)", "0,0,0,0")
            self.core.clearROI.assert_called_once()

    def test_property_write_stops_and_restarts_preview(self):
        with MicroManagerSession(self.sdk, self.profile) as session:
            session.start()
            adapter = MicroManagerControls(session)
            adapter.set_value("mm:Gain", "3")
            self.core.stopSequenceAcquisition.assert_called_once()
            self.assertEqual(self.core.startContinuousSequenceAcquisition.call_count, 2)
            self.assertEqual(adapter.read_controls()["mm:Gain"].value, "3")

    def test_thread_owns_frame_and_cleans_up(self):
        thread = self.thread()
        frames, errors = [], []
        def receive(image, raw):
            frames.append((image, raw))
            thread.stop()
        thread.frame_ready.connect(receive)
        thread.error.connect(lambda *args: errors.append(args))
        thread.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(frames), 1)
        image, payload = frames[0]
        array = payload.pixels
        self.assertEqual(image.pixelColor(0, 0).red(), 128)
        self.core.popNextImage.return_value[:] = 0
        self.assertEqual(int(array[0, 0]), 2048)
        array[:] = 0
        self.assertEqual(image.pixelColor(0, 0).red(), 128)
        self.core.stopSequenceAcquisition.assert_called_once()
        self.core.startContinuousSequenceAcquisition.assert_called_once_with(100.0)
        self.core.startSequenceAcquisition.assert_not_called()
        self.core.unloadAllDevices.assert_called_once()
        self.assertEqual(thread.controller.capabilities(), {})

    def test_external_trigger_arms_and_waits_without_preview_frames(self):
        self.core.setProperty("Camera", "TriggerMode", "Off")
        self.core.setProperty("Camera", "TriggerSelector", "FrameStart")
        self.core.setProperty("Camera", "TriggerSource", "Line0")
        self.core.setProperty("Camera", "TriggerActivation", "RisingEdge")
        self.core.getAllowedPropertyValues.return_value = ()
        self.core.getAllowedPropertyValues.side_effect = None
        self.core.getRemainingImageCount.return_value = 0
        self.core.isSequenceRunning.return_value = True
        thread = self.thread()
        thread.hardware_trigger_source = "Line0"
        errors, ready = [], []
        thread.error.connect(lambda *args: errors.append(args))
        thread.grabber_ready.connect(lambda: ready.append(True))
        with patch.object(thread, "msleep", side_effect=lambda ms: thread.stop()):
            thread.run()
        self.assertEqual(errors, [])
        self.assertEqual(ready, [True])
        self.assertEqual(thread.trigger_configuration["TriggerMode"], "On")
        self.assertEqual(self.core.getProperty("Camera", "TriggerSource"), "Line0")
        self.core.stopSequenceAcquisition.assert_called_once()

    def test_overflow_and_stopped_sequence_are_errors_with_cleanup(self):
        for overflow in (True, False):
            with self.subTest(overflow=overflow):
                core, sdk = fake_core()
                core.isBufferOverflowed.return_value = overflow
                core.getRemainingImageCount.return_value = 0
                core.isSequenceRunning.return_value = False
                thread = self.thread(sdk)
                errors = []
                thread.error.connect(lambda *args: errors.append(args))
                thread.run()
                self.assertEqual(len(errors), 1)
                core.stopSequenceAcquisition.assert_called_once()
                core.unloadAllDevices.assert_called_once()

    def test_preview_arm_and_restore_preserve_controls_and_flush_buffer(self):
        for name, value in {"TriggerMode": "Off", "TriggerSelector": "FrameStart",
                            "TriggerSource": "Line0", "TriggerActivation": "RisingEdge",
                            "AcquisitionFrameRateEnable": "1"}.items():
            self.core.setProperty("Camera", name, value)
        self.core.hasProperty.side_effect = lambda camera, name: name == "AcquisitionFrameRateEnable"
        self.core.getAllowedPropertyValues.side_effect = lambda camera, name: {
            "TriggerMode": ("On", "Off"), "TriggerSource": ("Software", "Line0")}.get(name, ())
        service = MicroManagerService(self.sdk)
        try:
            self.assertEqual(service.dispatch("open", (self.profile, ""))["trigger_configuration"], {})
            service.dispatch("set", ("exposure", 23000))
            armed = service.dispatch("timing", ("auto",))
            self.assertEqual(armed["trigger_configuration"]["TriggerMode"], "On")
            self.assertEqual(self.core.getProperty("Camera", "AcquisitionFrameRateEnable"), "0")
            restored = service.dispatch("timing", ("",))
            self.assertEqual(restored["trigger_configuration"], {})
            self.assertEqual(self.core.getProperty("Camera", "TriggerMode"), "Off")
            self.assertEqual(self.core.getExposure(), 23)
            self.assertEqual(self.core.getProperty("Camera", "AcquisitionFrameRateEnable"), "1")
            self.assertEqual(self.core.clearCircularBuffer.call_count, 4)
        finally:
            service.close()

    def test_partial_start_failure_still_stops_camera(self):
        self.core.startContinuousSequenceAcquisition.side_effect = RuntimeError("start failed")
        thread = self.thread()
        thread.run()
        self.core.stopSequenceAcquisition.assert_called_once()
        self.core.unloadAllDevices.assert_called_once()

    def spinnaker_controls(self):
        self.core.getDeviceLibrary.return_value = "SpinnakerC"
        names = ["Exposure", "Frame Rate", "Frame Rate Control Enabled", "Trigger Mode",
                 "Trigger Selector", "Trigger Source", "Trigger Activation"]
        self.core.getDevicePropertyNames.side_effect = lambda camera: names
        self.core.hasProperty.side_effect = lambda camera, name: name in names
        self.core.hasPropertyLimits.side_effect = lambda camera, name: name in {"Exposure", "Frame Rate"}
        for name, value in {"Trigger Mode": "On", "Trigger Selector": "FrameStart",
                            "Trigger Source": "Line0", "Trigger Activation": "FallingEdge",
                            "Frame Rate": "6", "Frame Rate Control Enabled": "1"}.items():
            self.core.setProperty("Camera", name, value)
        self.core.getAllowedPropertyValues.side_effect = lambda camera, name: {
            "Trigger Mode": ("Off", "On"), "Trigger Source": ("Software", "Line0"),
            "Trigger Selector": ("FrameStart",), "Trigger Activation": ("RisingEdge", "FallingEdge"),
        }.get(name, ())

    def test_spinnakerc_uses_actual_adapter_names_for_preview_arm_and_restore(self):
        self.spinnaker_controls()
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        preview = service.dispatch("open", (self.profile, ""))
        self.assertEqual(self.core.getProperty("Camera", "Trigger Mode"), "Off")
        self.assertEqual(preview["controls"]["fps"].value, 10)
        service.dispatch("set", ("fps", 5))
        service.dispatch("set", ("exposure", 23000))
        armed = service.dispatch("timing", ("auto",))
        self.assertEqual(armed["trigger_configuration"], {
            "Trigger Selector": "FrameStart", "Trigger Source": "Line0",
            "Trigger Activation": "RisingEdge", "Trigger Mode": "On"})
        self.assertEqual(armed["trigger_input"]["name"], "Line0")
        self.assertEqual(self.core.getProperty("Camera", "Frame Rate Control Enabled"), "0")
        restored = service.dispatch("timing", ("",))
        self.assertEqual(restored["trigger_configuration"], {})
        self.assertIsNone(restored["trigger_input"])
        self.assertEqual(self.core.getProperty("Camera", "Trigger Mode"), "Off")
        self.assertEqual(self.core.getProperty("Camera", "Frame Rate Control Enabled"), "1")
        self.assertEqual(restored["controls"]["fps"].value, 5)
        self.assertEqual(self.core.getExposure(), 23)

    def test_mm_adapter_cannot_silently_reset_triggering_when_sequence_starts(self):
        self.spinnaker_controls()
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        service.dispatch("open", (self.profile, ""))
        self.core.startContinuousSequenceAcquisition.side_effect = lambda _: self.core.setProperty(
            "Camera", "Trigger Mode", "Off")
        with self.assertRaisesRegex(RuntimeError, "settings changed while arming"):
            service.dispatch("timing", ("auto",))

    def test_tiscam_uses_external_mode_and_records_unexposed_settings(self):
        self.core.getDeviceLibrary.return_value = "TIScam"
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        service.dispatch("open", (self.profile, ""))
        service.dispatch("set", ("exposure", 23000))
        armed = service.dispatch("timing", ("auto",))
        self.assertEqual(armed["trigger_configuration"], {"TriggerMode": "External"})
        self.assertEqual(armed["trigger_input"]["not_exposed"],
                         ["TriggerSource", "TriggerSelector", "TriggerActivation"])
        # The TIS adapter's acquisition thread can wait forever for a pulse.
        # BURST must release that wait before requesting its blocking stop.
        def stop():
            self.assertEqual(self.core.getProperty("Camera", "TriggerMode"), "Internal")
        self.core.stopSequenceAcquisition.side_effect = stop
        restored = service.dispatch("timing", ("",))
        self.assertEqual(restored["trigger_configuration"], {})
        self.assertEqual(self.core.getExposure(), 23)
        service.dispatch("timing", ("auto",))
        service.close()  # Cleanup must also release the pulse wait.

    def test_unknown_mm_adapter_with_external_enum_is_not_assumed_supported(self):
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        service.dispatch("open", (self.profile, ""))
        with self.assertRaisesRegex(RuntimeError, "does not mean the camera lacks triggering"):
            service.dispatch("timing", ("auto",))
        self.assertEqual(self.core.getProperty("Camera", "TriggerMode"), "Internal")

    def test_spinnakerc_does_not_guess_between_multiple_physical_inputs(self):
        self.spinnaker_controls()
        self.core.setProperty("Camera", "Trigger Source", "Software")
        original = self.core.getAllowedPropertyValues.side_effect
        self.core.getAllowedPropertyValues.side_effect = lambda camera, name: (
            ("Software", "Line0", "Line1") if name == "Trigger Source" else original(camera, name))
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        service.dispatch("open", (self.profile, ""))
        with self.assertRaisesRegex(RuntimeError, "one-time setup"):
            service.dispatch("timing", ("auto",))
        self.assertEqual(self.core.getProperty("Camera", "Trigger Mode"), "Off")

    def test_missing_trigger_pulses_time_out_without_blocking_fetch(self):
        self.core.getRemainingImageCount.return_value = 0
        self.core.isSequenceRunning.return_value = True
        thread = self.thread()
        errors = []
        thread.error.connect(lambda *args: errors.append(args))
        with patch.object(thread.controller, "service"), \
                patch("threads.mmcore_camera_thread.time.monotonic", side_effect=[0, 6]):
            thread.run()
        self.assertIn("trigger source", errors[0][0])
        self.core.popNextImage.assert_not_called()
        self.core.unloadAllDevices.assert_called_once()

    def test_multiple_channels_are_not_silently_paired_as_one_camera(self):
        self.core.getNumberOfCameraChannels.return_value = 2
        thread = self.thread()
        errors = []
        thread.error.connect(lambda *args: errors.append(args))
        thread.run()
        self.assertIn("Multi-channel", errors[0][0])
        self.core.startSequenceAcquisition.assert_not_called()
        self.core.unloadAllDevices.assert_called_once()

    def test_setup_missing_bridge_explains_dependency(self):
        dialog = MicroManagerSetupDialog(None, unavailable="pymmcore unavailable")
        self.assertFalse(dialog.test.isEnabled())
        self.assertIn("pymmcore unavailable", dialog.status.text())
        dialog.close()

    def test_rgb_conversion_and_unsupported_layout(self):
        image, array = copy_mm_frame(np.array([[0x00123456]], np.uint32), 4, 8)
        self.assertEqual(array[0, 0].tolist(), [0x12, 0x34, 0x56])
        self.assertEqual(image.pixelColor(0, 0).green(), 0x34)
        with self.assertRaisesRegex(RuntimeError, "Unsupported"):
            copy_mm_frame(np.zeros((2, 3), np.float32), 1, 32)
        # Reported dynamic range is advisory; brighter values must saturate, not wrap.
        _, clipped = copy_mm_frame(np.array([[65535]], np.uint16), 1, 12)
        self.assertEqual(int(clipped[0, 0]), 255)

    def test_setup_validates_in_worker_and_saves_selected_camera(self):
        dialog = MicroManagerSetupDialog(self.sdk)
        dialog.installation.setText(self.profile["installation"])
        dialog.config.setText(self.profile["config"])
        dialog._probe()
        deadline = time.monotonic() + 3
        while dialog.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QThread.msleep(5)
        self.assertIsNone(dialog.worker)
        self.assertTrue(dialog.add.isEnabled())
        dialog.cameras.setCurrentText("Camera2")
        dialog._add()
        self.assertEqual(dialog.profiles[0]["camera"], "Camera2")
        self.assertEqual(dialog.profiles[0]["configured_mode"], {"width": 4, "height": 2})
        dialog._add()
        self.assertEqual(len(dialog.profiles), 1)
        self.core.unloadAllDevices.assert_called_once()
        dialog.config.setText("missing.cfg")
        self.assertFalse(dialog.add.isEnabled())
        dialog.close()

    def test_properties_queue_changes_and_lock_during_recording(self):
        with MicroManagerSession(self.sdk, self.profile) as session:
            adapter = MicroManagerControls(session)
            controller = CameraController()
            controller.open(adapter)
            panel = CameraControlPanel()
            panel.controller = controller
            dialog = CameraPropertiesDialog(panel)
            dialog.names.setCurrentIndex(dialog.names.findData("mm:Gain"))
            dialog.value.setText("4")
            dialog._apply()
            self.core.setProperty.assert_not_called()
            controller.service(adapter)
            self.core.setProperty.assert_called_with("Camera", "Gain", "4")
            panel.is_recording = True
            dialog._refresh()
            self.assertFalse(dialog.apply.isEnabled())
            dialog.close()
            panel.close()
            controller.close()


if __name__ == "__main__":
    unittest.main()
