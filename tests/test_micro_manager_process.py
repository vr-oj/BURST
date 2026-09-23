import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras.micro_manager_process import MicroManagerClient, MicroManagerCancelled
sys.path.pop(0)


class MicroManagerProcessTests(unittest.TestCase):
    def test_abrupt_helper_exit_is_an_error_not_a_parent_crash(self):
        with MicroManagerClient() as client:
            process = client.process
            process.kill()
            process.wait(timeout=5)
            with self.assertRaisesRegex(RuntimeError, "BURST remains open"):
                client.request("probe", {})
        self.assertIsNotNone(process.poll())

    def test_request_times_out_and_reaps_helper(self):
        with MicroManagerClient() as client:
            process = client.process
            with patch.object(client.connection, "send"):
                with self.assertRaisesRegex(RuntimeError, "did not respond"):
                    client.request("probe", {}, timeout=0.1)
        self.assertIsNotNone(process.poll())

    def test_cancel_reaps_helper(self):
        with MicroManagerClient(cancelled=lambda: True) as client:
            process = client.process
            with self.assertRaises(MicroManagerCancelled):
                client.request("probe", {})
        self.assertIsNotNone(process.poll())

    @unittest.skipUnless(importlib.util.find_spec("pymmcore"), "Micro-Manager bridge not installed")
    def test_configuration_error_round_trips_without_closing_parent(self):
        with MicroManagerClient() as client:
            with self.assertRaisesRegex(RuntimeError, "installation folder"):
                client.request("probe", {})
            self.assertIsNone(client.process.poll())

    @unittest.skipUnless(os.environ.get("BURST_TEST_MM_DIR"), "Native demo test needs compatible adapters")
    def test_native_demo_frames_with_qt_loaded_in_parent(self):
        from PyQt5.QtWidgets import QApplication
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "demo.cfg"
            config.write_text("Property,Core,Initialize,0\nDevice,Camera,DemoCamera,DCam\n"
                              "Property,Core,Initialize,1\nProperty,Core,Camera,Camera\n", encoding="utf-8")
            profile = {"installation": os.environ["BURST_TEST_MM_DIR"], "config": str(config), "camera": "Camera"}
            with MicroManagerClient() as client:
                result = client.request("probe", profile)
                self.assertEqual(result["selected"], "Camera")
            with MicroManagerClient() as client:
                snapshot = client.request("open", profile)
                self.assertIn("mmcore:Exposure (ms)", snapshot["controls"])
                client.request("set", "mmcore:Exposure (ms)", "20")
                self.assertEqual(float(client.request("snapshot")["controls"]["mmcore:Exposure (ms)"].value), 20)
                end = time.monotonic() + 5
                payload = None
                while payload is None and time.monotonic() < end:
                    payload = client.request("next")
                    time.sleep(0.005)
                self.assertIsNotNone(payload)
                self.assertEqual(payload[0].ndim, 2)
                self.assertEqual(payload[1], 1)
                self.assertIn("ImageNumber", payload[3]["micro_manager"])
                client.request("set", "mmcore:Sensor ROI (x,y,width,height)", "0,0,64,32")
                client.request("set", "pixel_format", "16bit")
                end = time.monotonic() + 5
                resized = None
                while resized is None and time.monotonic() < end:
                    resized = client.request("next")
                    time.sleep(.005)
                self.assertEqual(resized[0].shape, (32, 64))
                self.assertEqual(str(resized[0].dtype), "uint16")
                with self.assertRaisesRegex(RuntimeError, "8/16-bit"):
                    client.request("set", "pixel_format", "32bit")
                self.assertEqual(client.request("snapshot")["controls"]["pixel_format"].value, "16bit")
                client.request("set", "mmcore:Sensor ROI (x,y,width,height)", "0,0,0,0")
                restored = client.request("snapshot")["diagnostics"]
                self.assertGreater(restored["image_width"], 64)


if __name__ == "__main__":
    unittest.main()
