"""Plugin contract, isolated runtime and acquisition tests; no camera/Arduino I/O."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "buti_app"))
from burst_camera_plugin import Control, Frame, TriggerState
from burst_camera_plugin.worker import Service, controls_data, frame_data, trigger_data
from cameras.plugins import PluginManifest, load_plugins
from cameras.plugin_process import PluginClient, PluginCancelled, worker_path
from cameras.registry import CameraRegistry
from threads.plugin_camera_thread import PluginCameraThread, decode_frame
from threads.plugin_discovery_thread import PluginDiscoveryThread
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QThread, pyqtSignal
import numpy as np
sys.path.pop(0)

spec = importlib.util.spec_from_file_location("demo_fixture", ROOT / "examples/camera_plugin/adapter.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class TriggerCamera(demo.DemoCamera):
    """Fake SDK, explicitly separate from the installable preview-only example."""
    def __init__(self):
        super().__init__()
        self.external = False
        self.pending = []
        self.stop_count = 0
        self.corrupt_trigger = self.corrupt_exposure = False

    def configure_trigger(self, source):
        self.external = bool(source)
        if self.corrupt_exposure:
            self.values["exposure"] = 500
        return TriggerState(self.external, "Line1" if source else None,
                            {"Mode": "External" if source else "Internal"})

    def read_trigger(self):
        return TriggerState(self.external and not self.corrupt_trigger, "Line1" if self.external else None,
                            {"Mode": "External" if self.external else "Internal"})

    def start(self):
        super().start()
        self.pending.clear()  # Flush previous sequence, including preview backlog.

    def stop(self):
        super().stop()
        self.stop_count += 1

    def next_frame(self, timeout_ms):
        if self.external:
            return self.pending.pop(0) if self.pending else None
        return super().next_frame(timeout_ms)


class PluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / "lab_demo"
        shutil.copytree(ROOT / "examples/camera_plugin", self.folder, ignore=shutil.ignore_patterns("__pycache__"))
        self.data = json.loads((self.folder / "plugin.json").read_text())
        self.data["python"] = sys.executable
        self.manifest = self.write_manifest()

    def write_manifest(self):
        path = self.folder / "plugin.json"
        path.write_text(json.dumps(self.data), encoding="utf-8")
        return PluginManifest.read(path)

    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QThread.msleep(5)
        self.assertTrue(predicate())

    def test_discovery_controls_frames_and_normal_shutdown_in_separate_runtime(self):
        with PluginClient(self.manifest) as client:
            process = client.process
            devices = client.request("discover")
            self.assertNotEqual(process.pid, os.getpid())
            self.assertEqual(devices[0]["id"], "simulator")
            snapshot = client.request("open", "simulator", (640, 480, "Mono12"))
            self.assertEqual(snapshot["controls"]["exposure"]["unit"], "us")
            self.assertEqual(snapshot["trigger_configuration"], {})
            with self.assertRaisesRegex(RuntimeError, "outside the reported range"):
                client.request("set", "gain", 999)
            self.assertEqual(client.request("snapshot")["controls"]["gain"]["value"], 1)
            client.request("set", "exposure", 20000)
            client.request("set", "fps", 5)
            payload = client.request("next")
            image, frame = decode_frame(payload)
            self.assertEqual((image.width(), image.height()), (640, 480))
            self.assertEqual(frame.pixels.dtype, np.uint16)
            self.assertGreater(frame.pixels.max(), 255)
            self.assertEqual(frame.pixel_format, "Mono12")
            self.assertIsNone(frame.camera_frame_id)
            self.assertTrue(frame.metadata["simulated"])
            self.assertNotIn("adapter", sys.modules)
        self.assertIsNotNone(process.poll())

    def test_manifest_validation_duplicates_disabled_and_no_import(self):
        (self.folder / "adapter.py").write_text("raise RuntimeError('must not import during manifest scan')")
        plugins, errors = load_plugins([self.root])
        self.assertEqual(set(plugins), {"plugin:lab_demo"})
        self.assertFalse(errors)
        shutil.copytree(self.folder, self.root / "duplicate")
        plugins, errors = load_plugins([self.root])
        self.assertFalse(plugins)
        self.assertIn("Duplicate", " ".join(errors.values()))
        self.data.update(enabled=False, python="missing")
        (self.folder / "plugin.json").write_text(json.dumps(self.data))
        plugins, errors = load_plugins([self.root])
        self.assertEqual(set(plugins), {"plugin:lab_demo"})
        self.assertFalse(errors)
        self.data.update(enabled=True, api_version=999)
        with self.assertRaisesRegex(ValueError, "API 1"):
            self.write_manifest()
        self.data.update(api_version=1, python="missing")
        with self.assertRaisesRegex(ValueError, "environment not found"):
            self.write_manifest()
        self.data.update(python=sys.executable, id="ic4")
        with self.assertRaisesRegex(ValueError, "reserved"):
            self.write_manifest()

    def test_missing_sdk_helper_crash_timeout_and_cancel_leave_app_alive(self):
        for script, message, timeout in (
            ("import nonexistent_burst_test_sdk", "nonexistent_burst_test_sdk", 5),
            ("import os; os._exit(42)", "helper", 5),
            ("import time; time.sleep(30)", "did not respond", 0.25),
        ):
            with self.subTest(message=message):
                (self.folder / "adapter.py").write_text(script)
                with self.assertRaisesRegex(RuntimeError, message):
                    with PluginClient(self.manifest) as client:
                        process = client.process
                        client.request("discover", timeout=timeout)
                self.assertIsNotNone(process.poll())
        event = threading.Event()
        timer = threading.Timer(0.2, event.set)
        timer.start()
        try:
            with self.assertRaises(PluginCancelled):
                with PluginClient(self.manifest, cancelled=event.is_set) as client:
                    process = client.process
                    client.request("discover")
            self.assertIsNotNone(process.poll())
        finally:
            timer.join()

    def test_timing_preserves_image_settings_flushes_backlog_and_waits_without_pulses(self):
        camera = TriggerCamera()
        service = Service(camera)
        self.addCleanup(service.close)
        service.dispatch("open", ("simulator", None))
        service.dispatch("set", ("exposure", 23000))
        service.dispatch("set", ("gain", 2))
        for _ in range(2):
            camera.pending = [Frame(np.zeros((2, 3), dtype=np.uint8))]
            armed = service.dispatch("timing", ("auto",))
            self.assertEqual(armed["trigger_input"], "Line1")
            self.assertIsNone(service.dispatch("next", ()))
            self.assertEqual(camera.values["exposure"], 23000)
            self.assertEqual(camera.values["gain"], 2)
            camera.pending.append(Frame(np.full((2, 3), 1200, dtype=np.uint16), 12, 75,
                                        {"camera_timestamp_ns": 1234, "timestamp_clock": "device"}))
            _, frame = decode_frame(service.dispatch("next", ()))
            self.assertEqual(frame.camera_frame_id, 75)
            self.assertEqual(frame.metadata["camera_timestamp_ns"], 1234)
            with self.assertRaisesRegex(RuntimeError, "Stop recording"):
                service.dispatch("set", ("exposure", 1000))
            service.dispatch("timing", (None,))
            self.assertIsNotNone(service.dispatch("next", ()))
        service.dispatch("timing", ("auto",))
        service.close()
        self.assertFalse(camera.streaming)

    def test_unverified_timing_changed_exposure_and_unsupported_trigger_fail_closed(self):
        for attr in ("corrupt_trigger", "corrupt_exposure"):
            camera = TriggerCamera()
            service = Service(camera)
            try:
                service.dispatch("open", ("simulator", None))
                setattr(camera, attr, True)
                with self.assertRaises(RuntimeError):
                    service.dispatch("timing", ("auto",))
                self.assertIsNone(service.source)
                self.assertEqual(service.trigger, {})
            finally:
                service.close()
        with PluginClient(self.manifest) as client:
            client.request("open", "simulator", None)
            with self.assertRaisesRegex(RuntimeError, "no external trigger"):
                client.request("timing", "auto")
            with self.assertRaisesRegex(RuntimeError, "no external trigger"):
                client.request("snapshot")

    def test_invalid_controls_and_frame_layouts_rejected_without_losing_raw_depth(self):
        for trigger in (TriggerState(1, "Line1", {"Mode": "External"}),
                        TriggerState(True, "Line1", ["External"]),
                        TriggerState(True, "Software", {"Mode": "External"})):
            with self.assertRaises(RuntimeError):
                trigger_data(trigger, "auto")
        for controls in ({"exposure": Control(10, unit="ms")},
                         {"gain": Control("Sensitivity", value_type="enum")},
                         {"auto_gain": Control("Once", choices=("Off", "Once"))},
                         {"mystery": Control(1)}):
            with self.assertRaises(ValueError):
                controls_data(controls)
        with self.assertRaises(ValueError):
            frame_data(Frame(np.zeros((2, 3), dtype=np.float32)))
        pixels = np.array([[0, 1234, 4095]], dtype=np.uint16)
        wire = frame_data(Frame(pixels, 12))
        pixels[:] = 0
        image, frame = decode_frame(wire)
        self.assertEqual(frame.pixels.tolist(), [[0, 1234, 4095]])
        self.assertEqual(image.pixelColor(2, 0).red(), 255)
        wire["pixels"] = b"short"
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            decode_frame(wire)

    def test_async_discovery_partial_results_and_registry_routing(self):
        bad = self.root / "bad"
        shutil.copytree(self.folder, bad)
        data = self.data | {"id": "broken_plugin"}
        (bad / "plugin.json").write_text(json.dumps(data))
        (bad / "adapter.py").write_text("raise ImportError('Missing vendor runtime')")
        with patch.dict(os.environ, BURST_CAMERA_PLUGIN_PATH=str(self.root)):
            registry = CameraRegistry("auto", importer=lambda name: (_ for _ in ()).throw(ImportError()))
            backends = registry.refresh_plugins()
        search = PluginDiscoveryThread(backends)
        search.start()
        self.wait_for(lambda: not search.isRunning())
        self.assertIn("plugin:broken_plugin", search.errors)
        device = search.results["plugin:lab_demo"][0]
        backends[device.backend].devices = [device]
        self.assertIn(device, registry.discover_cameras())
        self.assertEqual(registry.list_modes(device)[0].as_tuple(), (320, 240, "Mono12"))
        thread = registry.get_thread(device)
        self.assertIsInstance(thread, PluginCameraThread)
        frames, errors = [], []
        thread.frame_ready.connect(lambda image, frame: frames.append(frame))
        thread.error.connect(lambda *args: errors.append(args))
        thread.start()
        try:
            self.wait_for(lambda: bool(frames))
            self.assertEqual(errors, [])
            self.assertEqual(thread.controller.capabilities()["gain"].unit, "camera units")
        finally:
            thread.stop()
            self.assertTrue(thread.wait(3000))

    def test_packaged_bridge_path(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(self.root), create=True):
            self.assertEqual(worker_path(), self.root / "buti_app/burst_camera_plugin/worker.py")

    def test_default_mode_and_bounded_discovery_cancellation(self):
        plugins, _ = load_plugins([self.root])
        backend = plugins["plugin:lab_demo"]
        device = backend.probe()[0]
        device.native_info["modes"] = []
        modes = backend.list_modes(device)
        self.assertEqual(modes[0].as_tuple(), (0,0,"Default"))
        thread = backend.create_thread(device)
        thread.set_resolution(modes[0].as_tuple())
        self.assertIsNone(thread._resolution)
        (self.folder / "adapter.py").write_text("import time; time.sleep(20)")
        search = PluginDiscoveryThread(plugins)
        search.start()
        QThread.msleep(150)
        search.requestInterruption()
        self.assertTrue(search.wait(3000))
        self.assertFalse(search.results)

    def test_packaged_source_resources_work_outside_repository_with_external_runtime(self):
        packaged = self.root / "bundle" / "buti_app" / "burst_camera_plugin"
        shutil.copytree(ROOT / "buti_app/burst_camera_plugin", packaged, ignore=shutil.ignore_patterns("__pycache__"))
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(self.root / "bundle"), create=True):
            with PluginClient(self.manifest) as client:
                client.request("open", "simulator", None)
                image, frame = decode_frame(client.request("next"))
                self.assertEqual(frame.pixels.dtype, np.uint16)
                self.assertEqual(image.width(), 320)

    def test_gui_plugin_discovery_and_failed_arming_never_start_arduino(self):
        import main_window
        registry = CameraRegistry("plugin:lab_demo")
        with patch.dict(os.environ, BURST_CAMERA_PLUGIN_PATH=str(self.root)), \
                patch.object(main_window, "CameraRegistry", return_value=registry), \
                patch.object(main_window, "load_app_setting", side_effect=lambda key, default=None: default):
            window = main_window.MainWindow()
            try:
                self.wait_for(lambda: window.device_combo.currentData() is not None)
                self.assertTrue(window.device_combo.currentData().backend.startswith("plugin:"))
                self.assertEqual(window.device_combo.itemText(window.device_combo.count() - 1), "Micro-Manager Camera Setup…")
                window._on_start_stop_camera()
                self.wait_for(lambda: window._last_camera_frame_monotonic is not None)
                window._current_session_name = "plugin test"
                window._run_silent_recording_preflight = Mock(return_value=True)
                window._show_error_dialog = Mock()
                window._start_recording_files = Mock()
                window._send_serial_command = Mock()
                window._on_start_recording()
                self.wait_for(lambda: window._show_error_dialog.called)
                self.assertFalse(window._camera_armed)
                self.assertEqual(window._hardware_trigger_source, "auto")
                window._start_recording_files.assert_not_called()
                window._send_serial_command.assert_not_called()
            finally:
                if window.camera_thread is not None:
                    window.camera_thread.stop()
                    window.camera_thread.wait(4000)
                window.close()
                self.app.processEvents()

    def test_plugin_recording_uses_existing_sparse_pairing_and_restores_preview(self):
        import main_window
        import tifffile
        # Pulses are simulated by this test only, after the Arduino start command.
        # This fixture is not shipped as an externally triggered camera example.
        with (self.folder / "adapter.py").open("a", encoding="utf-8") as stream:
            stream.write('''
class TriggeredTestCamera(DemoCamera):
    external = False
    count = 0
    def configure_trigger(self, source):
        self.external = bool(source)
        return self.read_trigger()
    def read_trigger(self):
        return TriggerState(self.external, "Line1" if self.external else None,
                            {"Mode": "External" if self.external else "Internal"})
    def start(self):
        super().start()
        self.count = 0
    def next_frame(self, timeout_ms):
        from pathlib import Path
        if not self.external:
            return super().next_frame(timeout_ms)
        if Path("pulses").exists() and self.count < 2:
            self.count += 1
            return Frame(np.full((240,320), self.count * 1000, np.uint16), 12,
                         camera_frame_id=100+self.count, metadata={"simulated": True})
        time.sleep(timeout_ms / 1000)
        return None
''')
        self.data["entry_point"] = "adapter:TriggeredTestCamera"
        self.manifest = self.write_manifest()
        commands = []
        class SerialStub(QThread):
            data_ready = pyqtSignal(float, int, float, int, float)
            def isRunning(self):
                return True
            def send_command(self, command):
                commands.append(command)
                return True
            def stop(self):
                pass
        registry = CameraRegistry("plugin:lab_demo")
        with patch.dict(os.environ, BURST_CAMERA_PLUGIN_PATH=str(self.root)), \
                patch.object(main_window, "CameraRegistry", return_value=registry), \
                patch.object(main_window, "load_app_setting", side_effect=lambda key, default=None: default):
            window = main_window.MainWindow()
            serial = SerialStub()
            try:
                self.wait_for(lambda: window.device_combo.currentData() is not None)
                window._on_start_stop_camera()
                self.wait_for(lambda: window._last_camera_frame_monotonic is not None)
                window.camera_thread.controller.set_value("exposure", 23000)
                self.wait_for(lambda: window.camera_thread.controller.capabilities()["exposure"].value == 23000)
                window._serial_thread = serial
                window._current_session_name = "test"
                window._run_silent_recording_preflight = Mock(return_value=True)
                window._run_recording_completion_prompts = Mock()
                window._show_error_dialog = Mock()
                outdir = self.root / "Run1"
                outdir.mkdir()
                with patch.object(main_window, "get_next_run_folder", return_value=str(outdir)), \
                        patch("recording_manager.MIN_FREE_SPACE_GB", 0):
                    window._on_start_recording()
                    self.wait_for(lambda: window._recording_state == "recording")
                    self.assertTrue(window._camera_armed)
                    self.assertEqual(commands, ["G"])
                    self.assertEqual(window.camera_thread.trigger_input, "Line1")
                    serial.data_ready.emit(.1, 1, 0, 0, 10)
                    serial.data_ready.emit(.2, 1, 0, 0, 11)  # sparse Capture: no new image
                    serial.data_ready.emit(.3, 2, 0, 0, 12)
                    (self.folder / "pulses").write_text("two fake pulses")
                    self.wait_for(lambda: window._recorder_worker._frame_counter == 2)
                    window._on_stop_recording()
                    self.wait_for(lambda: window._recording_state == "idle" and not window._timing_transition)
                    self.assertEqual(commands, ["G", "S"])
                    self.assertEqual(window.camera_thread.controller.capabilities()["exposure"].value, 23000)
                    self.assertFalse(window._show_error_dialog.called)
                    self.assertEqual(window._last_recording_summary.status, "passed")
                    with tifffile.TiffFile(window._last_recording_paths["tiff"]) as stack:
                        self.assertEqual(len(stack.pages), 2)
                        for index, force in enumerate((10,12)):
                            self.assertEqual(stack.pages[index].asarray()[0,0], (index+1)*1000)
                            self.assertEqual(json.loads(stack.pages[index].description)["force"], force)
                    manifest = json.loads((outdir / "burst-run.json").read_text())
                    self.assertIn('"plugin_id": "lab_demo"', json.dumps(manifest))
            finally:
                if window._recording_state in {"preparing", "recording"}:
                    window._on_stop_recording()
                if window._recorder_thread:
                    self.wait_for(lambda: window._recorder_thread is None)
                window._serial_thread = None
                if window.camera_thread:
                    window.camera_thread.stop()
                    window.camera_thread.wait(4000)
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
