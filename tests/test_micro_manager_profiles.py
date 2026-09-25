import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras.controls import CameraController, CameraControl
from cameras.micro_manager_backend import MicroManagerSession, MicroManagerControls
from cameras.micro_manager_profiles import normalize_profile, read_profile, write_profile, profile_key
from cameras.micro_manager_process import MicroManagerService
from cameras.micro_manager_discovery import find_cameras, discover_library
from cameras.frame_data import FrameData
from ui.micro_manager_mapping import MicroManagerMappingDialog
from ui.micro_manager_setup import MicroManagerSetupDialog
from ui.control_panels.camera_control_panel import CameraControlPanel
from main_window import MainWindow
from PyQt5.QtWidgets import QApplication, QComboBox
from test_micro_manager import fake_core
sys.path.pop(0)


class ProfileAndControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        cfg = Path(self.folder.name) / "camera.cfg"
        cfg.write_text("# camera", encoding="utf-8")
        self.profile = dict(installation=self.folder.name, config=str(cfg), camera="Camera")
        self.core, self.sdk = fake_core()
        self.core.getPropertyType.side_effect = lambda camera, name: 3 if name == "Gain" else 1

    def controls(self, profile=None):
        session = MicroManagerSession(self.sdk, profile or self.profile).__enter__()
        self.addCleanup(session.close)
        return MicroManagerControls(session)

    def test_old_profile_migrates_and_mapping_round_trips(self):
        result = normalize_profile(self.profile)
        self.assertEqual(result["version"], 2)
        result["bindings"] = {"gain": {"property": "Gain", "unit": "camera units"}}
        path = Path(self.folder.name) / "shared.json"
        write_profile(path, result)
        self.assertEqual(read_profile(path), result)
        self.assertNotIn("version", self.profile)

    def test_invalid_mappings_are_data_errors(self):
        invalid = [{"bindings": {"gain": {"property": "Gain", "unit": "dB", "script": "anything"}}},
                   {"bindings": {"auto_gain": {"property": "GainAuto", "on": "On", "off": "On"}}},
                   {"timing": {"external": [{"property": "TriggerMode", "value": "On"}]}},
                   {"version": 99}]
        for extra in invalid:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                normalize_profile(dict(self.profile, **extra))

    def test_preview_only_mapping_round_trips_without_authorizing_external_recording(self):
        self.core.setProperty("Camera", "TriggerMode", "External")
        profile = normalize_profile(dict(self.profile, timing={
            "preview": [{"property": "TriggerMode", "value": "Internal"}]}))
        path = Path(self.folder.name) / "preview-only.json"
        write_profile(path, profile)
        self.assertEqual(read_profile(path), profile)
        controls = self.controls(profile).read_controls()
        dialog = MicroManagerMappingDialog(profile, controls)
        self.addCleanup(dialog.close)
        dialog._save()
        self.assertEqual(dialog.profile["timing"]["preview"], profile["timing"]["preview"])
        self.assertFalse(dialog.profile["timing"].get("external"))
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        service.dispatch("open", (profile, ""))
        self.assertEqual(self.core.getProperty("Camera", "TriggerMode"), "Internal")
        self.assertIsNotNone(service.dispatch("next", ()))
        with self.assertRaisesRegex(RuntimeError, "cannot yet configure external triggering"):
            service.dispatch("timing", ("auto",))
        self.assertEqual(service.trigger_configuration, {})
        self.assertEqual(self.core.getProperty("Camera", "TriggerMode"), "Internal")

    def test_stale_mapping_fails_before_acquisition(self):
        with self.assertRaisesRegex(ValueError, "missing property"):
            self.controls(dict(self.profile, bindings={"gain": {"property": "Missing", "unit": "dB"}}))
        self.core.startContinuousSequenceAcquisition.assert_not_called()

    def test_saved_binding_overrides_alias_and_converts_exposure_units(self):
        self.core.setProperty("Camera", "Integration", "0.01")
        adapter = self.controls(dict(self.profile, bindings={"exposure": {"property": "Integration", "unit": "s"}}))
        self.assertEqual(adapter.read_controls()["exposure"].value, 10000)
        adapter.set_value("exposure", 20000)
        self.assertEqual(self.core.getProperty("Camera", "Integration"), "0.02")
        self.assertEqual(self.core.getExposure(), 10)
        self.assertFalse(adapter.read_controls()["exposure"].limits_known)

    def test_ambiguous_alias_is_not_guessed(self):
        self.core.setProperty("Camera", "Frame Rate", "5")
        adapter = self.controls()
        self.assertNotIn("fps", adapter.read_controls())
        self.assertIn("Multiple", adapter.read_diagnostics()["control_issues"]["fps"])
        mapped = self.controls(dict(self.profile, bindings={"fps": {"property": "Frame Rate", "unit": "fps"}}))
        self.assertEqual(mapped.read_controls()["fps"].value, 5)

    def test_native_gain_units_integer_write_and_unbounded_ui(self):
        adapter = self.controls()
        adapter.set_value("gain", 3.0)
        self.assertEqual(self.core.getProperty("Camera", "Gain"), "3")
        with self.assertRaises(ValueError):
            adapter.set_value("gain", 3.5)
        controller = CameraController()
        controller.open(adapter)
        panel = CameraControlPanel()
        panel.set_controller(controller)
        panel._refresh_auto_values()
        self.assertFalse(panel.gain_spin.isHidden())
        self.assertTrue(panel.gain_spin.isEnabled())
        self.assertEqual(panel.gain_spin.decimals(), 0)
        panel.gain_spin.stepUp()
        controller.service(adapter)
        panel._refresh_auto_values()
        self.assertEqual(self.core.getProperty("Camera", "Gain"), "4")
        self.assertEqual(panel.gain_spin.value(), 4)
        self.assertFalse(panel.gain_slider.isEnabled())
        self.assertEqual(panel._unit_labels[panel.gain_spin].text(), "camera units")
        panel.close()

    def test_spaced_auto_alias_preserves_native_readback_and_values(self):
        self.core.setProperty("Camera", "Exposure Auto", "Enabled")
        self.core.getAllowedPropertyValues.side_effect = lambda camera, name: ("Disabled", "Enabled") if name == "Exposure Auto" else ()
        adapter = self.controls(dict(self.profile, bindings={
            "auto_exposure": {"property": "Exposure Auto", "on": "Enabled", "off": "Disabled"}}))
        self.assertEqual(adapter.read_controls()["auto_exposure"].value, "Continuous")
        adapter.set_value("auto_exposure", "Off")
        self.assertEqual(adapter.read_controls()["mm:Exposure Auto"].value, "Disabled")
        self.core.getAllowedPropertyValues.side_effect = lambda *args: ("Other",)
        with self.assertRaisesRegex(ValueError, "no longer offered"):
            adapter.read_controls()

    def test_stream_locked_format_is_changed_only_after_stopping(self):
        adapter = self.controls()
        self.core.isPropertyReadOnly.side_effect = lambda camera, name: name == "PixelType" and adapter.session.acquiring
        adapter.session.start()
        control = adapter.read_controls()["pixel_format"]
        self.assertTrue(control.writable)
        self.assertTrue(control.requires_stop)
        original = self.core.setProperty.side_effect
        def write(camera, name, value):
            self.assertFalse(adapter.session.acquiring)
            original(camera, name, value)
        self.core.setProperty.side_effect = write
        adapter.set_value("pixel_format", "8bit")
        self.assertTrue(adapter.session.acquiring)
        self.assertEqual(adapter.read_controls()["pixel_format"].value, "8bit")

    def test_unsupported_format_rolls_back_and_preview_restarts(self):
        adapter = self.controls()
        self.core.getImageBitDepth.side_effect = lambda: 32 if self.core.getProperty("Camera", "PixelType") == "32bit" else 16
        adapter.session.start()
        with self.assertRaisesRegex(ValueError, "8/16-bit"):
            adapter.set_value("pixel_format", "32bit")
        self.assertEqual(self.core.getProperty("Camera", "PixelType"), "16bit")
        self.assertTrue(adapter.session.acquiring)

    def test_packed_pixels_fail_before_streaming(self):
        self.core.getBytesPerPixel.return_value = 1
        adapter = self.controls()
        with self.assertRaisesRegex(ValueError, "Packed"):
            adapter.session.start()
        self.core.startContinuousSequenceAcquisition.assert_not_called()

    def test_rejected_fps_does_not_rewrite_rounded_maximum_on_rollback(self):
        self.core.setProperty("Camera", "AcquisitionFrameRate", "6.8346")
        self.core.hasPropertyLimits.return_value = False
        self.core.hasPropertyLimits.side_effect = None
        self.core.getPropertyType.side_effect = lambda *args: 2
        original = self.core.setProperty.side_effect
        def set_value(camera, name, value):
            if name == "AcquisitionFrameRate" and float(value) > 6.834599:
                raise RuntimeError("above physical maximum")
            original(camera, name, value)
        self.core.setProperty.side_effect = set_value
        adapter = self.controls()
        adapter.session.start()
        with self.assertRaisesRegex(RuntimeError, "above physical maximum"):
            adapter.set_value("fps", 10)
        self.assertTrue(adapter.session.acquiring)
        adapter.set_value("fps", 6.8346)
        self.assertEqual(adapter.read_controls()["fps"].value, 6.8346)

    def test_failed_roi_restores_previous_region(self):
        adapter = self.controls()
        def set_roi(x, y, w, h):
            if w == 3:
                raise RuntimeError("width must be aligned")
        self.core.setROI.side_effect = set_roi
        adapter.session.start()
        with self.assertRaisesRegex(RuntimeError, "aligned"):
            adapter.set_value("mmcore:Sensor ROI (x,y,width,height)", "0,0,3,2")
        self.assertEqual(self.core.setROI.call_args.args, (0, 0, 4, 2))
        self.assertTrue(adapter.session.acquiring)

    def test_ordered_saved_timing_and_image_settings_are_preserved(self):
        self.profile["timing"] = {"preview": [{"property": "TriggerMode", "value": "Internal"}],
                                 "external": [{"property": "TriggerMode", "value": "Internal"},
                                              {"property": "TriggerMode", "value": "External"}]}
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        service.dispatch("open", (self.profile,))
        service.dispatch("set", ("exposure", 25000))
        armed = service.dispatch("timing", ("auto",))
        self.assertEqual(armed["trigger_configuration"], {"TriggerMode": "External"})
        self.assertEqual(armed["trigger_input"]["selection"], "saved_mapping")
        with self.assertRaisesRegex(RuntimeError, "Stop recording"):
            service.dispatch("set", ("gain", 2))
        restored = service.dispatch("timing", ("",))
        self.assertEqual(restored["controls"]["exposure"].value, 25000)
        self.assertEqual(restored["trigger_configuration"], {})

    def test_timing_mapping_cannot_overwrite_image_controls(self):
        profile = dict(self.profile, timing={mode: [{"property": "Exposure", "value": "20"}]
                                           for mode in ("preview", "external")})
        with self.assertRaisesRegex(ValueError, "image settings"):
            self.controls(profile)

    def test_mapping_editor_saves_selected_property_and_unit(self):
        controls = self.controls().read_controls()
        dialog = MicroManagerMappingDialog(self.profile, controls)
        prop, unit, _, _ = dialog.rows["gain"]
        prop.setCurrentIndex(prop.findData("Gain"))
        unit.setCurrentText("camera units")
        dialog._save()
        self.assertEqual(dialog.profile["bindings"]["gain"], {"property": "Gain", "unit": "camera units"})
        dialog.close()

    def test_discovery_results_keep_mapping_and_remember_connection(self):
        profile = normalize_profile(dict(installation=self.folder.name, connection={"library": "DemoCamera", "device": "DCam"},
            bindings={"gain": {"property": "Gain", "unit": "camera units"}}))
        dialog = MicroManagerSetupDialog(True, [profile])
        self.assertEqual(dialog.installation.text(), self.folder.name)
        discovered = dict(profile, bindings={})
        dialog._found({"cameras": [{"profile": discovered, "controls": {}}], "issues": []})
        self.assertEqual(dialog.cameras.currentData(), discovered)
        self.assertTrue(dialog.add.isEnabled())
        dialog._add()
        self.assertEqual(len(dialog.profiles), 1)
        self.assertEqual(dialog.profiles[0]["bindings"], profile["bindings"])
        self.assertEqual(profile_key(profile), profile_key(discovered))
        dialog.close()

    def test_sensor_choices_are_native_and_locked_during_recording(self):
        combo = QComboBox()
        device = QComboBox()
        device.addItem("MM", NS(backend="micromanager"))
        controller = NS(capabilities=lambda: {"mm:Binning": CameraControl("1", choices=("1", "2")),
            "mmcore:Sensor ROI (x,y,width,height)": CameraControl("0,0,4,2")})
        state = NS(device_combo=device, resolution_combo=combo, camera_thread=NS(controller=controller),
                   _recording_state="idle", _camera_armed=False, _timing_transition="")
        MainWindow._update_micro_manager_resolution(state, 4, 2)
        self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                         ["4×2 (Current)", "Full sensor", "Custom sensor region…", "Binning 1", "Binning 2"])
        self.assertTrue(combo.isEnabled())
        state._recording_state = "preparing"
        MainWindow._update_micro_manager_resolution(state, 4, 2)
        self.assertFalse(combo.isEnabled())

    def test_metadata_is_owned_and_never_an_assumed_hardware_counter(self):
        class Metadata:
            def GetKeys(self): return ("ImageNumber", "ElapsedTime-ms")
            def GetSingleTag(self, key): return NS(GetValue=lambda: "123")
        self.sdk.Metadata = Metadata
        self.core.popNextImageMD.return_value = self.core.popNextImage.return_value
        service = MicroManagerService(self.sdk)
        self.addCleanup(service.close)
        service.dispatch("open", (self.profile,))
        pixels, _, _, metadata = service.dispatch("next", ())
        payload = FrameData.copy(pixels, metadata=metadata)
        metadata["micro_manager"]["ImageNumber"] = "changed"
        self.assertEqual(payload.metadata["micro_manager"]["ImageNumber"], "123")
        self.assertIsNone(payload.camera_frame_id)


class DiscoveryTests(unittest.TestCase):
    def test_deadline_retains_results_and_uses_separate_helpers(self):
        clock = [0]
        instances, requests = [], []
        class Client:
            def __init__(self, **kw): instances.append(self)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def request(self, method, *args, timeout):
                requests.append(timeout)
                clock[0] += 10
                if method == "inspect_installation":
                    return dict(installation="MM", libraries=["SpinnakerC", "A", "B", "C", "D", "E"])
                if args[1] == "A": raise RuntimeError("missing vendor DLL")
                if args[1] == "B": raise RuntimeError("helper exited")
                return {"cameras": [{"profile": {"physical_id": "same", "camera": "Cam"}}], "issues": []}
        result = find_cameras(["MM"], Client, clock=lambda: clock[0])
        self.assertEqual(len(result["cameras"]), 1)
        self.assertEqual(len(instances), 6)
        self.assertTrue(all(t <= 10 for t in requests))
        self.assertIn("60 seconds", result["issues"][-1])
        self.assertTrue(any("missing vendor DLL" in issue for issue in result["issues"]))
        self.assertTrue(any("helper exited" in issue for issue in result["issues"]))

    def test_cancel_keeps_found_camera(self):
        cancelled = [False]
        class Client:
            def __init__(self, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def request(self, method, *args, **kw):
                if method == "inspect_installation": return dict(installation="MM", libraries=["A", "B"])
                cancelled[0] = True
                return dict(cameras=[{"profile": {"camera": "Found"}}], issues=[])
        result = find_cameras(["MM"], Client, cancelled=lambda: cancelled[0])
        self.assertEqual(len(result["cameras"]), 1)
        self.assertIn("cancelled", result["issues"][-1])

    def test_spinnakerc_multiple_serials_and_missing_serial(self):
        core, sdk = fake_core()
        core.getAvailableDevices.return_value = ["Blackfly"]
        core.getAvailableDeviceTypes.return_value = [sdk.CameraDevice]
        core.setProperty("Camera", "Serial Number", "111")
        core.isPropertyPreInit.side_effect = lambda camera, name: name == "Serial Number"
        core.getAllowedPropertyValues.side_effect = lambda camera, name: ("111", "222") if name == "Serial Number" else ()
        with tempfile.TemporaryDirectory() as folder:
            result = discover_library(sdk, folder, "SpinnakerC")
            self.assertEqual([p["profile"]["serial"] for p in result["cameras"]], ["111", "222"])
            self.assertNotEqual(*[p["profile"]["physical_id"] for p in result["cameras"]])
            core.getAllowedPropertyValues.side_effect = lambda *args: ()
            result = discover_library(sdk, folder, "SpinnakerC")
            self.assertEqual(result["cameras"], [])
            self.assertIn("no camera serial", result["issues"][0])

    def test_unknown_preinit_and_native_dialog_need_guided_setup(self):
        core, sdk = fake_core()
        core.getAvailableDevices.return_value = ["Camera"]
        core.getAvailableDeviceTypes.return_value = [sdk.CameraDevice]
        core.supportsDeviceDetection.return_value = False
        with tempfile.TemporaryDirectory() as folder:
            for library in ("Unknown", "TIScam"):
                result = discover_library(sdk, folder, library)
                self.assertEqual(result["cameras"], [])
                self.assertTrue(result["issues"])
        core.initializeDevice.assert_not_called()

    def test_generic_adapter_uses_device_detection_before_initializing(self):
        core, sdk = fake_core()
        sdk.CanCommunicate = 1
        core.getAvailableDevices.return_value = ["Camera"]
        core.getAvailableDeviceTypes.return_value = [sdk.CameraDevice]
        core.supportsDeviceDetection.return_value = True
        core.detectDevice.return_value = sdk.CanCommunicate
        with tempfile.TemporaryDirectory() as folder:
            result = discover_library(sdk, folder, "Detectable")
        self.assertEqual(len(result["cameras"]), 1)
        core.detectDevice.assert_called_once_with("Camera")
        core.initializeDevice.assert_called_once_with("Camera")


if __name__ == "__main__":
    unittest.main()
