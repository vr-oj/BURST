import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
    import tifffile
except ImportError:  # pragma: no cover - optional recording dependencies
    np = None
    tifffile = None


APP_PATH = str(Path(__file__).parents[1] / "buti_app")
sys.path.insert(0, APP_PATH)
try:
    from utils.braid_connector import braid_launch_command, find_braid_application
    from utils.preflight import run_recording_preflight
    from utils.recording_recovery import (
        FINAL_MANIFEST_NAME,
        PARTIAL_MANIFEST_NAME,
        complete_manifest,
        create_partial_manifest,
        finalize_partial_pair,
        find_recoverable_manifests,
        recover_partial_recording,
        update_manifest_file_names,
    )
    from utils.recording_summary import RecordingSummary, format_bytes, format_duration
finally:
    sys.path.remove(APP_PATH)


class RecordingSummaryTests(unittest.TestCase):
    def test_summary_round_trip_and_display_helpers(self):
        summary = RecordingSummary(
            status="passed",
            samples_written=8,
            frames_written=8,
            duration_s=62.34,
            csv_size_bytes=1024,
        )

        restored = RecordingSummary.from_dict(summary.to_dict())

        self.assertTrue(restored.checks_passed)
        self.assertEqual(restored.status_title, "Capture checks passed")
        self.assertEqual(format_duration(restored.duration_s), "01:02.34")
        self.assertEqual(format_bytes(restored.csv_size_bytes), "1.0 KB")


class RecordingPreflightTests(unittest.TestCase):
    def test_healthy_preflight_is_silent_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_recording_preflight(
                serial_ready=True,
                camera_ready=True,
                camera_frame_age_s=0.1,
                session_name="Experiment A",
                device_run_active=False,
                results_root=directory,
                minimum_free_gb=0,
            )

        self.assertTrue(report.passed)
        self.assertEqual(report.failures, ())

    def test_preflight_reports_all_failed_readiness_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_recording_preflight(
                serial_ready=False,
                camera_ready=False,
                camera_frame_age_s=None,
                session_name=None,
                device_run_active=True,
                results_root=directory,
                minimum_free_gb=0,
            )

        self.assertFalse(report.passed)
        self.assertEqual(
            {check.label for check in report.failures},
            {"BUTI Arduino Box", "Camera", "Camera frames", "Recording session", "Device state"},
        )


class RecordingRecoveryTests(unittest.TestCase):
    @unittest.skipIf(tifffile is None, "TIFF recording dependencies are unavailable")
    def test_recovery_validates_and_preserves_readable_partial_data(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            partial_csv = folder / "recording_force.csv.partial"
            partial_tiff = folder / "recording_video.tif.partial"
            partial_csv.write_text(
                "time_s,frame_index,distance,cycle,force\n"
                "0.0,1,0.1,1,2.0\n"
                "0.5,2,0.2,1,3.0\n"
                "truncated,\n",
                encoding="utf-8",
            )
            with tifffile.TiffWriter(partial_tiff) as writer:
                writer.write(np.zeros((2, 2), dtype=np.uint8))
                writer.write(np.ones((2, 2), dtype=np.uint8))
            manifest = create_partial_manifest(
                directory,
                final_csv_name="recording_force.csv",
                final_tiff_name="recording_video.tif",
                partial_csv_name=partial_csv.name,
                partial_tiff_name=partial_tiff.name,
            )

            csv_path, tiff_path, summary = recover_partial_recording(manifest)

            self.assertEqual(summary.status, "recovered")
            self.assertEqual(summary.samples_written, 2)
            self.assertEqual(summary.frames_written, 2)
            self.assertTrue(any("unreadable" in issue for issue in summary.issues))
            self.assertTrue(Path(csv_path).exists())
            self.assertTrue(Path(tiff_path).exists())
            recovered_manifest = json.loads(
                (folder / FINAL_MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(recovered_manifest["state"], "recovered")

    def test_empty_interruption_marker_is_discarded_without_prompting(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = create_partial_manifest(
                directory,
                final_csv_name="recording_force.csv",
                final_tiff_name="recording_video.tif",
                partial_csv_name="recording_force.csv.partial",
                partial_tiff_name="recording_video.tif.partial",
            )

            recoverable = find_recoverable_manifests(directory)

            self.assertEqual(recoverable, [])
            self.assertFalse(Path(manifest).exists())

    def test_partial_pair_and_manifest_finalize_transactionally(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            partial_csv = folder / "recording_force.csv.partial"
            partial_tiff = folder / "recording_video.tif.partial"
            final_csv = folder / "recording_force.csv"
            final_tiff = folder / "recording_video.tif"
            partial_csv.write_text("time_s,frame_index,distance,cycle,force\n", encoding="utf-8")
            partial_tiff.write_bytes(b"TIFF data")
            manifest = create_partial_manifest(
                directory,
                final_csv_name=final_csv.name,
                final_tiff_name=final_tiff.name,
                partial_csv_name=partial_csv.name,
                partial_tiff_name=partial_tiff.name,
                acquisition={"session": "Experiment A"},
            )

            finalized_csv, finalized_tiff = finalize_partial_pair(
                str(partial_csv),
                str(partial_tiff),
                str(final_csv),
                str(final_tiff),
            )
            complete_manifest(
                manifest,
                RecordingSummary("passed", 1, 1, 0.0),
                csv_path=finalized_csv,
                tiff_path=finalized_tiff,
            )

            self.assertFalse((folder / PARTIAL_MANIFEST_NAME).exists())
            final_manifest = folder / FINAL_MANIFEST_NAME
            data = json.loads(final_manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "complete")
            self.assertEqual(data["acquisition"]["session"], "Experiment A")

            renamed_csv = folder / "specimen_force.csv"
            renamed_tiff = folder / "specimen_video.tif"
            final_csv.rename(renamed_csv)
            final_tiff.rename(renamed_tiff)
            update_manifest_file_names(directory, str(renamed_csv), str(renamed_tiff))
            updated = json.loads(final_manifest.read_text(encoding="utf-8"))
            self.assertEqual(updated["files"]["csv"], renamed_csv.name)
            self.assertEqual(updated["files"]["tiff"], renamed_tiff.name)

    def test_pair_finalization_rolls_back_if_second_destination_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            partial_csv = folder / "a.csv.partial"
            partial_tiff = folder / "a.tif.partial"
            final_csv = folder / "a.csv"
            final_tiff = folder / "a.tif"
            partial_csv.write_text("csv", encoding="utf-8")
            partial_tiff.write_bytes(b"tiff")
            final_tiff.write_bytes(b"existing")

            with self.assertRaises(FileExistsError):
                finalize_partial_pair(
                    str(partial_csv), str(partial_tiff), str(final_csv), str(final_tiff)
                )

            self.assertTrue(partial_csv.exists())
            self.assertTrue(partial_tiff.exists())
            self.assertFalse(final_csv.exists())


class BraidConnectorTests(unittest.TestCase):
    def test_mac_app_launch_uses_generic_open_argument(self):
        with patch("utils.braid_connector.sys.platform", "darwin"):
            program, arguments = braid_launch_command(
                "/Applications/BRAID.app", "/data/Run 2/specimen_video.tif"
            )

        self.assertEqual(program, "open")
        self.assertEqual(
            arguments,
            [
                "-n",
                "-a",
                "/Applications/BRAID.app",
                "--args",
                "--open",
                "/data/Run 2/specimen_video.tif",
            ],
        )

    def test_explicit_braid_path_is_detected_without_shared_code(self):
        with tempfile.TemporaryDirectory() as directory:
            app_path = Path(directory) / "BRAID.exe"
            app_path.write_bytes(b"")

            detected = find_braid_application(str(app_path))

        self.assertEqual(detected, str(app_path))


if __name__ == "__main__":
    unittest.main()
