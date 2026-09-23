import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras import CameraDeviceInfo, CameraRegistry
from cameras.models import physical_identity
from cameras.gentl_backend import GenTLBackend, GenTLSession, producer_files
from threads.gentl_camera_thread import GenTLCameraThread, copy_gentl_frame
sys.path.pop(0)


def fake_sdk():
    events = []
    info = NS(id_="device-42", model="Other SDK Camera", vendor="Vendor", serial_number="42")
    acquirer = Mock()
    acquirer.remote_device.node_map = NS()
    acquirer.start.side_effect = lambda: events.append("start")
    acquirer.stop.side_effect = lambda: events.append("stop")
    acquirer.destroy.side_effect = lambda: events.append("destroy")
    harvester = Mock(device_info_list=[info])
    harvester.create.return_value = acquirer
    harvester.reset.side_effect = lambda: events.append("reset")
    return NS(Harvester=lambda: harvester), acquirer, harvester, events


class GenTLTests(unittest.TestCase):
    def test_preview_arm_and_restore_acquisition(self):
        sdk, acquirer, _, events = fake_sdk()
        node_map = NS(**{name: NS(value=value, symbolics=choices) for name, value, choices in (
            ("TriggerMode", "Off", ("Off", "On")), ("TriggerSource", "Software", ("Software", "Line0")),
            ("TriggerSelector", "FrameStart", ("FrameStart",)), ("TriggerActivation", "RisingEdge", ("RisingEdge",)),
            ("AcquisitionMode", "Continuous", ("Continuous",)), ("AcquisitionFrameRateEnable", True, ()))})
        acquirer.remote_device.node_map = node_map
        acquirer.try_fetch.return_value = None
        genapi = NS(is_readable=lambda node: True, is_writable=lambda node: True)
        thread = GenTLCameraThread(sdk=sdk, genapi=genapi)
        thread.set_device_info({"producer": "vendor.cti", "id": "device-42"})
        thread.grabber_ready.connect(lambda: thread.request_timing("auto"))
        modes, errors = [], []
        def ready(armed):
            modes.append(armed)
            if armed:
                thread.request_timing("")
            else:
                thread.stop()
        thread.timing_ready.connect(ready)
        thread.error.connect(lambda *args: errors.append(args))
        thread.run()
        self.assertEqual(errors, [])
        self.assertEqual(modes, [True, False])
        self.assertEqual(node_map.TriggerMode.value, "Off")
        self.assertTrue(node_map.AcquisitionFrameRateEnable.value)
        self.assertEqual(events, ["start", "stop", "start", "stop", "start", "stop", "destroy", "reset"])

    def test_advertised_producer_paths_are_bounded_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vendor.cti"
            path.touch()
            (Path(directory) / "not-a-producer.dll").touch()
            with patch.dict(os.environ, {"GENICAM_GENTL64_PATH": directory, "BURST_GENTL_PATH": str(path)}):
                self.assertEqual(producer_files(), [str(path.resolve())])

    def test_discovery_uses_detached_identity_and_bad_producer_is_isolated(self):
        sdk, acquirer, harvester, events = fake_sdk()
        backend = GenTLBackend.__new__(GenTLBackend)
        backend.sdk, backend.genapi = sdk, Mock()
        harvester.add_file.side_effect = [OSError("bad DLL"), None]
        with patch("cameras.gentl_backend.producer_files", return_value=["bad.cti", "good.cti"]):
            device, = backend.discover()
        self.assertEqual((device.backend, device.serial, device.native_info),
                         ("gentl", "42", {"producer": "good.cti", "id": "device-42"}))
        self.assertEqual(events, ["reset", "reset"])
        self.assertIsInstance(backend.create_thread(device), GenTLCameraThread)

    def test_gentl_frame_uses_fixed_bit_depth_and_owns_storage(self):
        data = np.array([0, 16, 2048, 4095], dtype=np.uint16)
        image, array = copy_gentl_frame(NS(data=data, data_format="Mono12", width=2, height=2))
        data[:] = 0
        self.assertEqual(array.tolist(), [[0, 1], [128, 255]])
        array[:] = 0
        self.assertEqual(image.pixelColor(1, 1).red(), 255)

    def test_gentl_returns_buffer_before_stopping_and_destroying(self):
        sdk, acquirer, harvester, events = fake_sdk()
        buffer = Mock()
        data = np.array([1, 2, 3, 4], dtype=np.uint8)
        buffer.payload.components = [NS(data=data, data_format="Mono8", width=2, height=2)]
        def release():
            data[:] = 0
            events.append("queue")
        buffer.queue.side_effect = release
        acquirer.try_fetch.return_value = buffer
        thread = GenTLCameraThread(sdk=sdk, genapi=Mock())
        thread.set_device_info({"producer": "vendor.cti", "id": "device-42"})
        frames, errors = [], []
        thread.frame_ready.connect(lambda image, array: (frames.append((image, array)), thread.stop()))
        thread.error.connect(lambda *args: errors.append(args))
        thread.run()
        self.assertEqual(errors, [])
        self.assertEqual(frames[0][1].pixels.tolist(), [[1, 2], [3, 4]])
        self.assertEqual(events, ["start", "queue", "stop", "destroy", "reset"])

    def test_acquisition_failure_still_destroys_device(self):
        sdk, acquirer, harvester, events = fake_sdk()
        acquirer.start.side_effect = RuntimeError("in use")
        thread = GenTLCameraThread(sdk=sdk, genapi=Mock())
        thread.set_device_info({"producer": "vendor.cti", "id": "device-42"})
        errors = []
        thread.error.connect(lambda *args: errors.append(args))
        thread.run()
        self.assertEqual(len(errors), 1)
        self.assertEqual(events, ["destroy", "reset"])

    def test_installed_adapter_is_discovered_without_ui_changes(self):
        device = CameraDeviceInfo("other_sdk", "id", "Other camera")
        backend = NS(key="other_sdk", discover=lambda: [device])
        entry = NS(name="other_sdk", load=lambda: lambda: backend)
        broken = NS(name="broken", load=Mock(side_effect=ImportError("missing SDK")))
        registry = CameraRegistry(importer=Mock(side_effect=ImportError), plugin_entries=[entry, broken])
        self.assertEqual(registry.discover_cameras(), [device])

    def test_vendor_sdk_preferred_over_matching_gentl_but_not_unknown_usb(self):
        registry = CameraRegistry(importer=Mock(side_effect=ImportError), plugin_entries=[])
        native = CameraDeviceInfo("spinnaker", "sdk", "FLIR", "123", physical_id=physical_identity("FLIR", "123"))
        generic = CameraDeviceInfo("gentl", "cti", "FLIR via CTI", "123", physical_id=physical_identity("Teledyne FLIR", "123"))
        usb = CameraDeviceInfo("opencv", "0", "USB #0")
        registry.backends = {"spinnaker": NS(discover=lambda: [native]),
                             "gentl": NS(discover=lambda: [generic]), "opencv": NS(discover=lambda: [usb])}
        self.assertEqual(registry.discover_cameras(), [native, usb])


if __name__ == "__main__":
    unittest.main()
