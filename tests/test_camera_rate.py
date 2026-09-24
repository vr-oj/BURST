import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from utils.camera_rate import CameraRateMonitor, check_camera_rate
from utils.preflight import PreflightCheck, run_recording_preflight
sys.path.pop(0)


class CameraRateTests(unittest.TestCase):
    def test_warmup_and_reset_require_measurement(self):
        monitor = CameraRateMonitor()
        for i in range(20):
            monitor.observe(i / 10)
        self.assertIsNone(monitor.fps(1.9))
        monitor.reset()
        self.assertIsNone(monitor.fps(2))

    def test_ten_fps_passes_but_stalled_stream_does_not(self):
        monitor = CameraRateMonitor()
        for i in range(51):
            monitor.observe(i / 10)
        self.assertTrue(check_camera_rate(monitor.fps(5)).passed)
        self.assertFalse(check_camera_rate(monitor.fps(6)).passed)
        self.assertFalse(check_camera_rate(monitor.fps(11)).passed)

    def test_low_rate_or_camera_limit_blocks_recording(self):
        self.assertFalse(check_camera_rate(6.83).passed)
        self.assertFalse(check_camera_rate(10, maximum=6.83).passed)
        self.assertFalse(check_camera_rate(10, configured=6.83).passed)
        self.assertFalse(check_camera_rate(None).passed)
        self.assertTrue(check_camera_rate(10).passed)

    def test_rate_failure_blocks_otherwise_ready_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_recording_preflight(
                serial_ready=True, camera_ready=True, camera_frame_age_s=0,
                session_name="Session 1", device_run_active=False,
                results_root=directory, minimum_free_gb=0,
                camera_rate_check=PreflightCheck("Camera rate", False, "6.83 FPS"))
        self.assertFalse(result.passed)
        self.assertEqual([c.label for c in result.failures], ["Camera rate"])

    def test_five_fps_target_accepts_slower_camera_but_still_checks_capacity(self):
        self.assertTrue(check_camera_rate(6.84, maximum=6.84, target=5).passed)
        self.assertTrue(check_camera_rate(5, configured=5, target=5).passed)
        self.assertFalse(check_camera_rate(4, target=5).passed)
        self.assertFalse(check_camera_rate(6, maximum=4, target=5).passed)
        self.assertFalse(check_camera_rate(None, target=5).passed)
