import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tifffile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage

sys.path.insert(0, str(Path(__file__).parents[1] / "buti_app"))
from cameras.frame_data import FrameData
from cameras.trigger import configure_external_trigger
from recording_manager import RecordingManager
from utils.buti_protocol import BoxObservation
from utils.preflight import run_recording_preflight
from utils.recording_files import rename_recording_pair
from utils.recording_recovery import recover_partial_recording, find_recoverable_manifests
from threads.serial_thread import SerialThread
from playback_window import PlaybackLoader
sys.path.pop(0)


class BoxCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.disk = patch("recording_manager.MIN_FREE_SPACE_GB", 0)
        self.disk.start()
        self.addCleanup(self.disk.stop)

    def recorder(self, folder, mode="box", timing="software"):
        recorder = RecordingManager(folder, acquisition_metadata={"capture_mode": mode, "timing_mode": timing})
        outputs = []
        recorder.finalized.connect(lambda *args: outputs.append(args))
        recorder.start_recording()
        self.addCleanup(recorder.stop_recording)
        return recorder, outputs

    def test_sparse_capture_keeps_all_rows_and_maps_saved_images(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder)
            image = QImage(2, 2, QImage.Format_Grayscale8)
            image.fill(128)
            original = np.array([[0, 1024], [32768, 65535]], dtype=np.uint16)
            for i in range(16):
                recorder.append_force(i / 5, i // 5, 0, 0, i)
                recorder.append_frame(image, FrameData.copy(original, pixel_format="Mono16"))
            recorder.request_stop()
            csv_path, tiff_path, summary = outputs[0]
            self.assertEqual(summary.status, "passed")
            self.assertEqual((summary.samples_written, summary.frames_written, summary.images_requested), (16, 3, 3))
            with open(csv_path, newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 16)
            self.assertEqual([int(r["sample_index"]) for r in rows if r["image_requested"] == "1"], [6, 11, 16])
            with tifffile.TiffFile(tiff_path) as stack:
                self.assertEqual([json.loads(p.description)["sample_index"] for p in stack.pages], [6, 11, 16])
                self.assertEqual(stack.pages[0].asarray().dtype, np.uint16)
                np.testing.assert_array_equal(stack.pages[0].asarray(), original)
            loaded = []
            loader = PlaybackLoader(tiff_path, csv_path)
            loader.loaded.connect(lambda forces, image, total: loaded.append((forces, total)))
            loader.run()
            self.assertEqual(loaded, [([5.0, 10.0, 15.0], 3)])

    def test_none_counter_and_explicit_force_only_produce_csv_without_tiff(self):
        for mode in ("box", "force_only"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                recorder, outputs = self.recorder(folder, mode)
                for i in range(12):
                    recorder.append_force(i / 5, 0 if mode == "box" else i, 0, 0, i)
                recorder.request_stop()
                csv_path, tiff_path, summary = outputs[0]
                self.assertEqual(tiff_path, "")
                self.assertEqual(summary.status, "passed")
                self.assertEqual(summary.images_requested, 0)
                renamed, empty = rename_recording_pair(csv_path, tiff_path, "force-only")
                self.assertTrue(Path(renamed).is_file())
                self.assertEqual(empty, "")
                manifest = json.loads((Path(folder) / "burst-run.json").read_text())
                self.assertEqual(manifest["files"]["tiff"], "")

    def test_counter_phase_is_not_guessed_at_start(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder)
            recorder.append_force(20, 100, 0, 0, 1)
            recorder.append_force(20.2, 100, 0, 0, 1)
            recorder.request_stop()
            self.assertEqual(outputs[0][2].images_requested, 0)

    def test_clock_reset_stops_recording_and_marks_review(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder)
            stopped = []
            recorder.synchronization_lost.connect(stopped.append)
            recorder.append_force(3, 2, 0, 0, 1)
            recorder.append_force(0, 0, 0, 0, 1)
            self.assertEqual(len(stopped), 1)
            self.assertEqual(outputs[0][2].status, "warning")

    def test_requested_images_still_trip_lag_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder)
            for i in range(8):
                recorder.append_force(i / 5, i, 0, 0, 1)
            self.assertFalse(recorder.is_recording)
            self.assertEqual(outputs[0][2].status, "warning")
            self.assertGreater(outputs[0][2].pending_samples, 0)

    def test_force_only_recovery_without_a_tiff(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder, "force_only")
            recorder.append_force(0, 0, 0, 0, 1)
            recorder.append_force(.2, 0, 0, 0, 2)
            recorder.csv_file.close()
            recorder.csv_file = None
            recorder.is_recording = False
            recorder._recovery_flush_timer.stop()
            manifests = find_recoverable_manifests(folder)
            self.assertEqual(len(manifests), 1)
            csv_path, tiff_path, summary = recover_partial_recording(manifests[0])
            self.assertTrue(Path(csv_path).is_file())
            self.assertEqual(tiff_path, "")
            self.assertEqual(summary.pending_samples, 0)
            self.assertEqual(summary.images_requested, 0)

    def test_observed_capture_can_change_without_reconfiguring_burst(self):
        box = BoxObservation()
        for i in range(31):
            box.observe(i / 5, i // 5)
        self.assertEqual(box.divisor, 5)
        self.assertAlmostEqual(box.sample_hz, 5)
        self.assertAlmostEqual(box.image_hz, 1)
        for i in range(31, 41):
            box.observe(i / 5, 6 + i - 30)
        self.assertEqual(box.divisor, 1)
        box.reset()
        self.assertIsNone(box.divisor)
        self.assertIsNone(box.sample_hz)

    def test_serial_transport_refuses_unsupported_commands(self):
        serial = SerialThread(port="test")
        serial.running = True
        for command in ("H", "R", "Z", "G\nR"):
            self.assertFalse(serial.send_command(command))
        self.assertTrue(serial.command_queue.empty())
        self.assertTrue(serial.send_command("G"))
        self.assertTrue(serial.send_command("S"))

    def test_force_only_preflight_does_not_require_camera(self):
        with tempfile.TemporaryDirectory() as folder:
            report = run_recording_preflight(serial_ready=True, camera_ready=False,
                camera_frame_age_s=None, session_name="test", device_run_active=False,
                results_root=folder, minimum_free_gb=0, camera_required=False)
            self.assertTrue(report.passed)

    def test_trigger_setting_readback_is_required(self):
        nodes = {"TriggerMode": "Off"}
        configured = configure_external_trigger(nodes.__getitem__, nodes.__setitem__, "Line1")
        self.assertEqual(configured["TriggerMode"], "On")
        self.assertEqual(configured["TriggerSource"], "Line1")
        with self.assertRaisesRegex(RuntimeError, "readback"):
            configure_external_trigger(lambda name: "Off", nodes.__setitem__, "Line1")
        self.assertEqual(nodes["TriggerMode"], "Off")
        with self.assertRaisesRegex(RuntimeError, "physical"):
            configure_external_trigger(nodes.__getitem__, nodes.__setitem__, "Software")

    def test_armed_trigger_preflight_does_not_require_a_preview_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            common = dict(serial_ready=True, camera_ready=True, camera_frame_age_s=None,
                session_name="test", device_run_active=False, results_root=folder, minimum_free_gb=0)
            self.assertFalse(run_recording_preflight(**common).passed)
            self.assertTrue(run_recording_preflight(**common, hardware_armed=True).passed)

    def test_external_triggers_pair_in_both_arrival_orders(self):
        for image_first in (False, True):
            with self.subTest(image_first=image_first), tempfile.TemporaryDirectory() as folder:
                recorder, outputs = self.recorder(folder, timing="external_trigger")
                image = QImage(2, 2, QImage.Format_Grayscale8)
                image.fill(32)
                for i in range(1, 4):
                    if image_first:
                        recorder.append_frame(image, FrameData.copy(np.full((2, 2), i, dtype=np.uint16)))
                    recorder.append_force(i / 5, i, 0, 0, i * 10)
                    if not image_first:
                        recorder.append_frame(image, FrameData.copy(np.full((2, 2), i, dtype=np.uint16)))
                recorder.request_stop()
                recorder._force_finalize()
                self.assertEqual(outputs[0][2].status, "passed")
                self.assertEqual(outputs[0][2].frames_written, 3)
                with tifffile.TiffFile(outputs[0][1]) as stack:
                    for i, page in enumerate(stack.pages, 1):
                        self.assertEqual(json.loads(page.description)["force"], i * 10)
                        self.assertEqual(page.asarray()[0, 0], i)

    def test_external_trigger_requires_zeroed_counter(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder, timing="external_trigger")
            stopped = []
            recorder.synchronization_lost.connect(stopped.append)
            recorder.append_force(1, 8, 0, 0, 1)
            self.assertFalse(recorder.is_recording)
            self.assertIn("ZERO", stopped[0])

    def test_extra_triggered_images_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder, timing="external_trigger")
            recorder.append_force(0, 0, 0, 0, 1)
            image = QImage(2, 2, QImage.Format_Grayscale8)
            recorder.append_frame(image, None)
            recorder.request_stop()
            recorder._force_finalize()
            self.assertEqual(outputs[0][2].status, "warning")
            self.assertIn("no matching Arduino", " ".join(outputs[0][2].issues))

    def test_missing_trigger_times_out_using_wall_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder, timing="external_trigger")
            recorder.append_force(0, 0, 0, 0, 1)
            recorder.append_force(.2, 1, 0, 0, 1)
            last = recorder._pending_samples[0][6]
            with patch("recording_manager.time.monotonic", return_value=last + 1.1):
                recorder._flush_recovery_outputs()
            self.assertFalse(recorder.is_recording)
            self.assertEqual(outputs[0][2].status, "warning")

    def test_camera_counter_gap_or_duplicate_stops_before_wrong_pair_is_saved(self):
        for frame_id in (10, 12, 1):
            with self.subTest(frame_id=frame_id), tempfile.TemporaryDirectory() as folder:
                recorder, outputs = self.recorder(folder, timing="external_trigger")
                image = QImage(2, 2, QImage.Format_Grayscale8)
                recorder.append_force(.1, 1, 0, 0, 10)
                recorder.append_frame(image, FrameData.copy(np.zeros((2, 2), np.uint8), camera_frame_id=10))
                recorder.append_force(.2, 2, 0, 0, 20)
                recorder.append_frame(image, FrameData.copy(np.zeros((2, 2), np.uint8), camera_frame_id=frame_id))
                self.assertFalse(recorder.is_recording)
                self.assertEqual(outputs[0][2].frames_written, 1)
                self.assertEqual(outputs[0][2].status, "warning")

    def test_queued_preview_frame_is_excluded_from_triggered_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder, outputs = self.recorder(folder, timing="external_trigger")
            image = QImage(2, 2, QImage.Format_Grayscale8)
            recorder.append_frame(image, FrameData.copy(np.zeros((2, 2), np.uint8),
                received_monotonic=recorder._recording_started_monotonic - 1, camera_frame_id=100))
            recorder.append_force(.1, 1, 0, 0, 10)
            recorder.append_frame(image, FrameData.copy(np.ones((2, 2), np.uint8), camera_frame_id=200))
            recorder.stop_recording()
            self.assertEqual(outputs[0][2].frames_written, 1)
            with tifffile.TiffFile(outputs[0][1]) as stack:
                self.assertEqual(json.loads(stack.pages[0].description)["pixels"]["camera_frame_id"], 200)
