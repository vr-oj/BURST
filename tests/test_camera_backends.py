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
from cameras.micro_manager_backend import MicroManagerBackend
from threads.sdk_camera_thread import SDKCameraThread
from threads.mmcore_camera_thread import MMCoreCameraThread
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

    def test_ic4_preview_arm_and_restore_without_reopening_or_resetting_exposure(self):
        from threads import sdk_camera_thread
        nodes = {name: NS(value=value, entries=[NS(name=n) for n in choices]) for name, value, choices in (
            ("TriggerMode", "Off", ("Off", "On")), ("TriggerSource", "Software", ("Software", "Line0")),
            ("TriggerSelector", "FrameStart", ("FrameStart",)), ("TriggerActivation", "RisingEdge", ("RisingEdge",)),
            ("AcquisitionMode", "Continuous", ("Continuous",)), ("ExposureAuto", "Off", ("Off", "Continuous")),
            ("GainAuto", "Off", ("Off", "Continuous")))}
        exposure = NS(value=10000)
        rate_enable = NS(value=True)
        class Props:
            def __iter__(self):
                return iter(())
            def find_enumeration(self, name):
                return nodes[name]
            def find_float(self, name):
                return exposure if name == "ExposureTime" else NS(value=0)
            def find_boolean(self, name):
                return rate_enable
        grabber = Mock(device_property_map=Props())
        sdk = NS(Grabber=lambda: grabber, Library=Mock(), LogLevel=NS(INFO=1), LogTarget=NS(STDERR=1),
                 QueueSink=Mock(), PixelFormat=NS(Mono8=1, Mono16=2),
                 StreamSetupOption=NS(ACQUISITION_START=1))
        modes, errors = [], []
        with patch.object(sdk_camera_thread, "ic4", sdk), \
                patch.dict(sys.modules, {"imagingcontrol4": sdk}), \
                patch.object(sdk_camera_thread, "IC4Controls", return_value=NS(read_controls=lambda: {})):
            thread = SDKCameraThread()
            thread.set_device_info(NS(model_name="Test", serial="1"))
            def preview_ready():
                exposure.value = 23000
                thread.request_timing("auto")
            def timing_ready(armed):
                modes.append(armed)
                if armed:
                    thread.request_timing("")
                else:
                    thread.stop()
            thread.grabber_ready.connect(preview_ready)
            thread.timing_ready.connect(timing_ready)
            thread.error.connect(lambda *args: errors.append(args))
            thread.run()
        self.assertEqual(errors, [])
        self.assertEqual(modes, [True, False])
        self.assertEqual(nodes["TriggerMode"].value, "Off")
        self.assertEqual(nodes["TriggerSource"].value, "Line0")
        self.assertEqual(exposure.value, 23000)
        self.assertTrue(rate_enable.value)
        self.assertEqual(grabber.device_open.call_count, 1)
        self.assertEqual(grabber.stream_setup.call_count, 3)

    def test_unified_discovery_and_backend_failure_isolation(self):
        sdk = NS(Library=Mock(), LogLevel=NS(INFO=1), LogTarget=NS(STDERR=1),
                 DeviceEnum=NS(devices=lambda: [NS(model_name="DMK", serial="123", unique_name="usb-id")]))
        generic = CameraDeviceInfo("micromanager", "0", "Camera — Micro-Manager")
        registry = CameraRegistry(importer=Mock(side_effect=ImportError))
        registry.backends = {"ic4": IC4Backend(sdk), "broken": Mock(discover=Mock(side_effect=RuntimeError)),
                             "micromanager": Mock(discover=lambda: [generic])}
        devices = registry.discover_cameras()
        self.assertEqual([d.backend for d in devices], ["ic4", "micromanager"])
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
        self.assertIsInstance(MicroManagerBackend(True).create_thread(
            CameraDeviceInfo("micromanager", "0", "Camera", native_info={})), MMCoreCameraThread)

    def test_registry_only_loads_ic4_and_micro_manager_even_with_all_enabled(self):
        importer = Mock(side_effect=ImportError("not installed"))
        for selection in ("auto", "all", "ic4,micromanager"):
            importer.reset_mock()
            registry = CameraRegistry(selection, importer=importer)
            self.assertEqual([call.args[0] for call in importer.call_args_list], ["imagingcontrol4", "pymmcore"])
            self.assertEqual(set(registry.unavailable), {"ic4", "micromanager"})

    def test_removed_backend_filters_cannot_fall_back_or_load_a_vendor_sdk(self):
        importer = Mock()
        registry = CameraRegistry("spinnaker,gentl,opencv", importer=importer)
        self.assertEqual(registry.discover_cameras(), [])
        importer.assert_not_called()

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
            increment_mode = NS(name="NONE")
            increment_reads = 0
            @property
            def increment(self):
                self.increment_reads += 1
                raise RuntimeError("continuous property")
        props = Mock()
        props.find_float.return_value = FloatNode()
        props.find_enumeration.side_effect = RuntimeError("missing")
        adapter = IC4Controls(NS(device_property_map=props))
        self.assertEqual(adapter.read_controls()["exposure"].increment, 0)
        adapter.read_controls()
        self.assertEqual(props.find_float.return_value.increment_reads, 0)

    def test_ic4_discrete_increment_is_preserved(self):
        node = NS(value=10, minimum=0, maximum=100, increment=0.25,
                  increment_mode=NS(name="INCREMENT"))
        props = Mock()
        props.find_float.return_value = node
        props.find_enumeration.side_effect = RuntimeError("missing")
        self.assertEqual(IC4Controls(NS(device_property_map=props)).read_controls()["gain"].increment, 0.25)

    def test_ic4_lists_maximum_when_current_mode_is_640_and_restores_geometry(self):
        nodes = {"OffsetX": NS(value=144, minimum=0), "OffsetY": NS(value=64, minimum=0)}
        class Dimension:
            minimum = 1
            def __init__(self, value, maximum, offset):
                self.value, self.sensor_max, self.offset = value, maximum, offset
            @property
            def maximum(self):
                return self.sensor_max - nodes[self.offset].value
        nodes.update(Width=Dimension(640, 2448, "OffsetX"), Height=Dimension(480, 2048, "OffsetY"))
        class PixelFormat:
            entries = [NS(name="Mono8"), NS(name="Mono16"), NS(name="Unavailable")]
            _value = "Mono16"
            @property
            def value(self):
                return self._value
            @value.setter
            def value(self, value):
                if value == "Unavailable":
                    raise RuntimeError("unsupported")
                self._value = value
                # Exercise restoration even if switching pixel format changes geometry.
                nodes["Width"].value = 640
                nodes["Height"].value = 480
        pf = PixelFormat()
        def enumeration(name):
            if name == "PixelFormat":
                return pf
            raise RuntimeError("missing")
        props = NS(find_integer=lambda name: nodes[name], find_enumeration=enumeration)
        grabber = Mock(device_property_map=props)
        backend = IC4Backend(NS(Grabber=lambda: grabber))
        modes = backend.list_modes(CameraDeviceInfo("ic4", "camera", "DMK", native_info="native"))
        self.assertEqual(modes[0].as_tuple(), (2448, 2048, "Mono8"))
        self.assertEqual({m.as_tuple() for m in modes}, {
            (2448, 2048, "Mono8"), (2448, 2048, "Mono16"),
            (1224, 1024, "Mono8"), (1224, 1024, "Mono16"),
            (612, 512, "Mono8"), (612, 512, "Mono16"),
            (640, 480, "Mono8"), (640, 480, "Mono16"),
        })
        self.assertEqual(pf.value, "Mono16")
        self.assertEqual({name: node.value for name, node in nodes.items()},
                         {"OffsetX": 144, "OffsetY": 64, "Width": 640, "Height": 480})
        grabber.device_close.assert_called_once()

    def test_ic4_acquisition_defaults_and_cleanup_are_preserved(self):
        from threads import sdk_camera_thread
        values = {}
        class Props:
            def __iter__(self):
                return iter(())
            def node(self, name):
                if name not in values:
                    values[name] = NS(value=0, minimum=0, maximum=100000, increment=1,
                                      entries=[NS(name="Continuous")])
                return values[name]
            find_float = find_integer = find_enumeration = node
        grabber = Mock(device_property_map=Props())
        sdk = Mock(Grabber=Mock(return_value=grabber))
        with patch.object(sdk_camera_thread, "ic4", sdk), patch.dict(sys.modules, {"imagingcontrol4": sdk}):
            thread = SDKCameraThread()
            thread.set_device_info(NS(model_name="DMK", serial="123"))
            thread.set_resolution((640, 480, "Mono8"))
            grabber.stream_setup.side_effect = lambda *args, **kwargs: thread.stop()
            thread.run()
        self.assertEqual(values["ExposureTime"].value, 10000)
        self.assertEqual(values["Gain"].value, 5)
        self.assertEqual(values["ExposureAuto"].value, "Continuous")
        self.assertEqual(values["GainAuto"].value, "Continuous")
        self.assertEqual(values["TriggerMode"].value, "Off")
        self.assertEqual(values["PixelFormat"].value, "Mono8")
        self.assertEqual((values["Width"].value, values["Height"].value), (640, 480))
        grabber.stream_stop.assert_called_once()
        grabber.device_close.assert_called_once()
        self.assertIsNone(thread.grabber)
        self.assertIsNone(thread._device_info)

if __name__ == "__main__":
    unittest.main()
