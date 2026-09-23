import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras import CameraRegistry
from cameras.spinnaker_backend import SpinnakerBackend, SpinnakerSession, SpinnakerControls
from threads.spinnaker_camera_thread import SpinnakerCameraThread, copy_spinnaker_frame
sys.path.pop(0)


class Entry:
    def __init__(self, name, value=0):
        self.name, self.value = name, value
    def GetSymbolic(self):
        return self.name
    def GetValue(self):
        return self.value


class Node:
    def __init__(self, value, minimum=0, maximum=4096, choices=(), writable=True):
        self.value, self.minimum, self.maximum = value, minimum, maximum
        self.choices, self.writable = choices, writable
    def GetValue(self):
        return self.value
    def SetValue(self, value):
        self.value = value
    def GetMin(self):
        return self.minimum
    def GetMax(self):
        return self.maximum
    def GetInc(self):
        return 1
    def GetCurrentEntry(self):
        return Entry(self.value)
    def GetEntries(self):
        return [Entry(name, i) for i, name in enumerate(self.choices)]
    def GetEntryByName(self, name):
        return Entry(name, self.choices.index(name)) if name in self.choices else None
    def SetIntValue(self, value):
        self.value = self.choices[value]


class Image:
    def __init__(self, events, name="Mono8", incomplete=False):
        self.events, self.name, self.incomplete = events, name, incomplete
        self.data = np.array([[10, 20, 30, 40], [50, 60, 70, 80]], dtype=np.uint8)
    def IsIncomplete(self):
        return self.incomplete
    def GetPixelFormatName(self):
        return self.name
    def GetNDArray(self):
        return self.data
    def Release(self):
        self.events.append("image-release")
        self.data[:] = 0  # Simulate immediate native-buffer reuse.


def fake_sdk():
    events = []
    nodes = {
        "DeviceModelName": Node("Blackfly S"), "DeviceSerialNumber": Node("1234"),
        "DeviceVendorName": Node("FLIR"), "DeviceID": Node("flir-usb-1234"),
        "AcquisitionMode": Node("Continuous", choices=("Continuous",)),
        "TriggerMode": Node("Off", choices=("Off", "On")),
        "PixelFormat": Node("Mono8", choices=("Mono8", "Mono16", "RGB8")),
        "Width": Node(4, 1, 4096), "Height": Node(2, 1, 3072),
    }
    nodemap = NS(GetNode=lambda name: nodes.get(name))
    camera = Mock()
    camera.GetTLDeviceNodeMap.return_value = nodemap
    camera.GetNodeMap.return_value = nodemap
    camera.Init.side_effect = lambda: events.append("init")
    camera.BeginAcquisition.side_effect = lambda: events.append("begin")
    camera.EndAcquisition.side_effect = lambda: events.append("end")
    camera.DeInit.side_effect = lambda: events.append("deinit")
    image = Image(events)
    camera.GetNextImage.return_value = image
    cameras = Mock()
    cameras.GetSize.return_value = 1
    cameras.GetByIndex.return_value = camera
    cameras.Clear.side_effect = lambda: events.append("clear")
    system = Mock()
    system.GetCameras.return_value = cameras
    system.ReleaseInstance.side_effect = lambda: events.append("release")
    sdk = NS(System=NS(GetInstance=lambda: system),
        CStringPtr=lambda n: n, CFloatPtr=lambda n: n, CIntegerPtr=lambda n: n,
        CEnumerationPtr=lambda n: n, CBooleanPtr=lambda n: n, CEnumEntryPtr=lambda n: n,
        IsReadable=lambda n: n is not None, IsWritable=lambda n: bool(n and getattr(n, "writable", False)),
        ImageProcessor=Mock, PixelFormat_RGB8=1, PixelFormat_Mono8=2,
        SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR=1, SPINNAKER_ERR_TIMEOUT=-1011)
    return sdk, camera, system, image, events


class SpinnakerTests(unittest.TestCase):
    def test_rate_clamping_is_reported(self):
        sdk, camera, _, _, _ = fake_sdk()
        node = Node(5, 1, 6.83)
        camera.GetNodeMap.return_value = NS(GetNode=lambda name: node)
        controls = SpinnakerControls(NS(sdk=sdk, camera=camera))
        with self.assertRaisesRegex(RuntimeError, "6.83"):
            controls.set_value("fps", 10)
        self.assertEqual(node.value, 6.83)
        node.maximum = 30
        controls.set_value("fps", 10)
        self.assertEqual(node.value, 10)

    def test_discovery_detaches_identity_and_releases_system(self):
        sdk, camera, system, image, events = fake_sdk()
        registry = CameraRegistry(importer=lambda name: sdk if name == "PySpin" else (_ for _ in ()).throw(ImportError()))
        device, = registry.discover_cameras()
        self.assertEqual((device.backend, device.id, device.serial), ("spinnaker", "flir-usb-1234", "1234"))
        self.assertIn("Blackfly S", device.display_name)
        self.assertIsInstance(device.native_info, str)
        self.assertEqual(events, ["clear", "release"])
        self.assertIsInstance(registry.get_thread(device), SpinnakerCameraThread)

    def test_modes_are_bounded_without_writing_camera(self):
        sdk, camera, system, image, events = fake_sdk()
        backend = SpinnakerBackend(sdk)
        device, = backend.discover()
        modes = backend.list_modes(device)
        self.assertEqual(len(modes), 12)
        self.assertEqual(modes[0].as_tuple(), (4, 2, "Mono8"))
        self.assertEqual(events[-4:], ["init", "deinit", "clear", "release"])

    def test_acquisition_owns_frames_and_cleans_up_in_order(self):
        sdk, camera, system, image, events = fake_sdk()
        thread = SpinnakerCameraThread(sdk=sdk)
        thread.set_device_info("flir-usb-1234")
        thread.set_resolution((4, 2, "Mono8"))
        frames, errors = [], []
        def receive(qimage, array):
            frames.append((qimage, array))
            thread.stop()
        thread.frame_ready.connect(receive)
        thread.error.connect(lambda *error: errors.append(error))
        thread.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(frames), 1)
        qimage, payload = frames[0]
        array = payload.pixels
        self.assertEqual(array[0].tolist(), [10, 20, 30, 40])
        self.assertEqual(qimage.pixelColor(0, 0).red(), 10)
        array[:] = 99
        self.assertEqual(qimage.pixelColor(0, 0).red(), 10)
        self.assertEqual(events, ["init", "begin", "image-release", "end", "deinit", "clear", "release"])
        self.assertEqual(thread.controller.capabilities(), {})

    def test_initialization_and_acquisition_failures_release_resources(self):
        for operation, tail in (("Init", ["clear", "release"]),
                                ("BeginAcquisition", ["deinit", "clear", "release"]),
                                ("GetNextImage", ["end", "deinit", "clear", "release"])):
            with self.subTest(operation=operation):
                sdk, camera, system, image, events = fake_sdk()
                getattr(camera, operation).side_effect = RuntimeError("device in use/disconnected")
                thread = SpinnakerCameraThread(sdk=sdk)
                thread.set_device_info("flir-usb-1234")
                errors = []
                thread.error.connect(lambda *error: errors.append(error))
                thread.run()
                self.assertEqual(len(errors), 1)
                self.assertEqual(events[-len(tail):], tail)

    def test_camera_list_failure_still_releases_system(self):
        sdk, camera, system, image, events = fake_sdk()
        system.GetCameras.side_effect = RuntimeError("driver failure")
        with self.assertRaises(RuntimeError):
            with SpinnakerSession(sdk):
                pass
        self.assertEqual(events, ["release"])

    def test_conversion_is_sdk_fixed_conversion_and_copied(self):
        sdk, camera, system, image, events = fake_sdk()
        image.name = "Mono16"
        converted = Image(events)
        processor = Mock()
        processor.Convert.return_value = converted
        qimage, array = copy_spinnaker_frame(sdk, image, processor)
        processor.Convert.assert_called_once_with(image, sdk.PixelFormat_Mono8)
        self.assertEqual(array[0, 0], 10)
        self.assertEqual(qimage.pixelColor(0, 0).red(), 10)
        self.assertEqual(events, ["image-release"])


if __name__ == "__main__":
    unittest.main()
