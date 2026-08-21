import csv
import json
import logging
import os
import shutil
import time
from collections import deque

import numpy as np
import tifffile
from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage

from utils.config import MIN_FREE_SPACE_GB
from utils.frame_transform import transform_qimage
from utils.recording_recovery import (
    complete_manifest,
    create_partial_manifest,
    discard_empty_partial_manifest,
    finalize_partial_pair,
)
from utils.recording_summary import RecordingSummary


log = logging.getLogger(__name__)


class RecordingManager(QObject):
    """Manage synchronized writing of force data and transformed camera frames."""

    ready_for_acquisition = pyqtSignal()
    finalized = pyqtSignal(str, str, object)
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)
    warning_occurred = pyqtSignal(str)

    def __init__(
        self,
        output_dir,
        *,
        normalized_roi=None,
        mirror_horizontal=False,
        mirror_vertical=False,
        acquisition_metadata=None,
        parent=None,
    ):
        super().__init__(parent)
        self.output_dir = output_dir
        self.normalized_roi = tuple(normalized_roi) if normalized_roi else None
        self.mirror_horizontal = bool(mirror_horizontal)
        self.mirror_vertical = bool(mirror_vertical)
        self.acquisition_metadata = dict(acquisition_metadata or {})

        self._csv_path = None
        self._tiff_path = None
        self._final_csv_path = None
        self._final_tiff_path = None
        self._partial_manifest_path = None
        self.csv_file = None
        self.csv_writer = None
        self.tif_writer = None
        self._first_frame_shape = None

        self.is_recording = False
        self._got_first_sample = False
        self._accept_force = False
        self._stop_requested = False
        self._finished_emitted = False
        self._close_failed = False
        self._mismatch_reported = False

        self._frame_counter = 0
        self._last_device_time = 0
        self._first_device_time = None
        self._first_frame_index = None
        self._last_frame_index = None
        self._frame_index_issues = []
        self._frames_written = 0
        self._samples_written = 0
        self._pending_samples = deque()

        self._finalize_timer = QTimer(self)
        self._finalize_timer.setSingleShot(True)
        self._finalize_timer.setInterval(2000)
        self._finalize_timer.timeout.connect(self._force_finalize)
        self._recovery_flush_timer = QTimer(self)
        self._recovery_flush_timer.setInterval(1000)
        self._recovery_flush_timer.timeout.connect(self._flush_recovery_outputs)

    @pyqtSlot()
    def start_recording(self):
        """Prepare output paths, then signal that the hardware may start."""

        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"recording_{timestamp}"
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            _total, _used, free = shutil.disk_usage(self.output_dir)
        except Exception as exc:
            self._fail_setup(f"Unable to prepare the recording folder: {exc}")
            return

        if free < MIN_FREE_SPACE_GB * 1024**3:
            gb_free = free / 1024**3
            self._fail_setup(
                f"Not enough disk space for recording ({gb_free:.2f} GB available; "
                f"{MIN_FREE_SPACE_GB} GB required)."
            )
            return

        self._final_csv_path = os.path.join(
            self.output_dir, f"{base_name}_force.csv"
        )
        self._final_tiff_path = os.path.join(
            self.output_dir, f"{base_name}_video.tif"
        )
        self._csv_path = f"{self._final_csv_path}.partial"
        self._tiff_path = f"{self._final_tiff_path}.partial"
        self._first_frame_shape = None
        self.is_recording = True
        self._accept_force = True
        self._got_first_sample = False
        self._stop_requested = False
        self._finished_emitted = False
        self._close_failed = False
        self._mismatch_reported = False
        self._frame_counter = 0
        self._last_device_time = 0
        self._first_device_time = None
        self._first_frame_index = None
        self._last_frame_index = None
        self._frame_index_issues.clear()
        self._frames_written = 0
        self._samples_written = 0
        self._pending_samples.clear()

        try:
            self._partial_manifest_path = create_partial_manifest(
                self.output_dir,
                final_csv_name=os.path.basename(self._final_csv_path),
                final_tiff_name=os.path.basename(self._final_tiff_path),
                partial_csv_name=os.path.basename(self._csv_path),
                partial_tiff_name=os.path.basename(self._tiff_path),
                acquisition=self.acquisition_metadata,
            )
        except OSError as exc:
            self.is_recording = False
            self._fail_setup(f"Unable to create the recording recovery manifest: {exc}")
            return

        log.info(
            "Ready to record partial files -> CSV: %s; TIFF: %s",
            self._csv_path,
            self._tiff_path,
        )
        self.ready_for_acquisition.emit()

    def _fail_setup(self, message: str) -> None:
        log.error(message)
        self.error_occurred.emit(message)
        self._emit_finished_once()

    def _open_outputs(self) -> bool:
        try:
            self.csv_file = open(self._csv_path, "w", newline="")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(
                ["time_s", "frame_index", "distance", "cycle", "force"]
            )
            self.tif_writer = tifffile.TiffWriter(self._tiff_path, bigtiff=True)
        except Exception as exc:
            log.exception("Failed to open recording output")
            self.error_occurred.emit(f"Failed to open recording files: {exc}")
            self._close_failed = True
            self.stop_recording()
            return False
        self._got_first_sample = True
        self._recovery_flush_timer.start()
        log.info("Recording files opened: %s and %s", self._csv_path, self._tiff_path)
        return True

    @pyqtSlot()
    def _flush_recovery_outputs(self):
        """Periodically push buffered recording data out for crash recovery."""

        try:
            if self.csv_file:
                self.csv_file.flush()
            if self.tif_writer:
                file_handle = getattr(self.tif_writer, "filehandle", None)
                if file_handle is not None and hasattr(file_handle, "flush"):
                    file_handle.flush()
        except Exception as exc:
            self._recovery_flush_timer.stop()
            self._close_failed = True
            log.exception("Unable to flush partial recording files")
            self.error_occurred.emit(
                f"Unable to prepare recording data for crash recovery: {exc}"
            )

    @pyqtSlot(float, int, float, int, float)
    def append_force(self, time_s, frame_idx, distance, cycle, force):
        if not self.is_recording or not self._accept_force:
            return
        if not self._got_first_sample and not self._open_outputs():
            return
        try:
            self.csv_writer.writerow([time_s, frame_idx, distance, cycle, force])
            if self._first_device_time is None:
                self._first_device_time = time_s
                self._first_frame_index = int(frame_idx)
            elif self._last_frame_index is not None:
                expected = self._last_frame_index + 1
                if int(frame_idx) != expected and len(self._frame_index_issues) < 5:
                    self._frame_index_issues.append(
                        f"Device frame index changed from {self._last_frame_index} "
                        f"to {int(frame_idx)}."
                    )
            self._last_device_time = time_s
            self._last_frame_index = int(frame_idx)
            self._samples_written += 1
            self._pending_samples.append(
                (time_s, frame_idx, distance, cycle, force)
            )
        except Exception as exc:
            log.exception("Error writing CSV row")
            self._close_failed = True
            self.error_occurred.emit(f"Error writing CSV: {exc}")
        self._check_stop_condition()

    @pyqtSlot(QImage, object)
    def append_frame(self, qimage, raw):
        del raw  # The argument keeps the camera buffer alive until this slot runs.
        if not self.is_recording or not self._got_first_sample:
            return
        if not self._pending_samples:
            return
        try:
            transformed, transform_metadata = transform_qimage(
                qimage,
                self.normalized_roi,
                mirror_horizontal=self.mirror_horizontal,
                mirror_vertical=self.mirror_vertical,
            )
            arr = self._qimage_to_numpy(transformed)
            if self._first_frame_shape is None:
                self._first_frame_shape = arr.shape
            time_s, frame_idx, distance, cycle, force = self._pending_samples.popleft()
            metadata = {
                "time_s": time_s,
                "frameIdx": frame_idx,
                "distance": distance,
                "cycle": cycle,
                "force": force,
                "frame_transform": transform_metadata,
            }
            self.tif_writer.write(arr, description=json.dumps(metadata))
            self._frame_counter += 1
            self._frames_written += 1
        except Exception as exc:
            log.exception("Error writing TIFF frame %d", self._frame_counter)
            self._close_failed = True
            self.error_occurred.emit(f"Error writing video frame: {exc}")
        self._check_stop_condition()

    @pyqtSlot()
    def request_stop(self):
        """Stop accepting force samples and drain already-paired camera frames."""

        if not self.is_recording or self._stop_requested:
            return
        self._stop_requested = True
        self._accept_force = False
        self._finalize_timer.start()
        self._check_stop_condition()

    def _check_stop_condition(self):
        if self._stop_requested and not self._pending_samples:
            self.stop_recording()

    @pyqtSlot()
    def _force_finalize(self):
        if not self.is_recording:
            return
        if self._pending_samples or self._frames_written != self._samples_written:
            self._report_mismatch()
        self.stop_recording()

    def _report_mismatch(self):
        if self._mismatch_reported:
            return
        self._mismatch_reported = True
        message = (
            "Recording finalized with a synchronization mismatch: "
            f"{self._samples_written} samples, {self._frames_written} frames."
        )
        log.warning(message)
        self.warning_occurred.emit(message)

    @pyqtSlot()
    def stop_recording(self):
        """Close files, emit finalized paths when valid, and finish exactly once."""

        if not self.is_recording:
            self._emit_finished_once()
            return
        self.is_recording = False
        self._accept_force = False
        self._finalize_timer.stop()
        self._recovery_flush_timer.stop()
        pending_samples = len(self._pending_samples)
        close_ok = not self._close_failed
        if self._got_first_sample and self._frames_written != self._samples_written:
            self._report_mismatch()

        try:
            if self.tif_writer:
                self.tif_writer.close()
        except Exception as exc:
            close_ok = False
            log.exception("Error closing TIFF")
            self.error_occurred.emit(f"Error closing TIFF: {exc}")
        finally:
            self.tif_writer = None

        try:
            if self.csv_file:
                self.csv_file.close()
        except Exception as exc:
            close_ok = False
            log.exception("Error closing CSV")
            self.error_occurred.emit(f"Error closing CSV: {exc}")
        finally:
            self.csv_file = None
            self.csv_writer = None

        if close_ok and self._got_first_sample and self._samples_written > 0:
            issues = list(self._frame_index_issues)
            if self._frames_written != self._samples_written:
                issues.append(
                    f"Counts differ: {self._samples_written} force samples and "
                    f"{self._frames_written} video frames."
                )
            if pending_samples:
                issues.append(
                    f"{pending_samples} force sample(s) had no paired video frame."
                )
            duration = (
                0.0
                if self._first_device_time is None
                else max(0.0, self._last_device_time - self._first_device_time)
            )
            summary = RecordingSummary(
                status="warning" if issues else "passed",
                samples_written=self._samples_written,
                frames_written=self._frames_written,
                duration_s=duration,
                pending_samples=pending_samples,
                first_frame_index=self._first_frame_index,
                last_frame_index=self._last_frame_index,
                issues=issues,
            )
            try:
                final_csv, final_tiff = finalize_partial_pair(
                    self._csv_path,
                    self._tiff_path,
                    self._final_csv_path,
                    self._final_tiff_path,
                )
            except Exception as exc:
                close_ok = False
                log.exception("Unable to finalize partial recording files")
                self.error_occurred.emit(
                    f"Recording files remain recoverable but could not be finalized: {exc}"
                )
            else:
                summary.csv_size_bytes = os.path.getsize(final_csv)
                summary.tiff_size_bytes = os.path.getsize(final_tiff)
                try:
                    complete_manifest(
                        self._partial_manifest_path,
                        summary,
                        csv_path=final_csv,
                        tiff_path=final_tiff,
                    )
                except Exception as exc:
                    log.exception("Unable to complete the recording manifest")
                    summary.status = "warning"
                    summary.issues.append(
                        f"The recording manifest could not be finalized: {exc}"
                    )
                    discard_empty_partial_manifest(self._partial_manifest_path)
                self.finalized.emit(final_csv, final_tiff, summary)
        elif not self._got_first_sample:
            discard_empty_partial_manifest(self._partial_manifest_path)
            for path in (self._csv_path, self._tiff_path):
                if path:
                    try:
                        os.unlink(path)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        log.warning("Unable to remove unused partial file %s", path)
        self._got_first_sample = False
        self._frame_counter = 0
        log.info("Recording stopped and files closed.")
        self._emit_finished_once()

    def _emit_finished_once(self) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self.finished.emit()

    def _qimage_to_numpy(self, qimage):
        fmt = qimage.format()
        if fmt in (QImage.Format_Grayscale8, QImage.Format_Indexed8):
            width, height = qimage.width(), qimage.height()
            ptr = qimage.bits()
            ptr.setsize(qimage.byteCount())
            padded = np.frombuffer(ptr, np.uint8).reshape(
                (height, qimage.bytesPerLine())
            )
            return padded[:, :width].copy()

        qimg = qimage.convertToFormat(QImage.Format_ARGB32)
        width, height = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        padded = np.frombuffer(ptr, np.uint8).reshape(
            (height, qimg.bytesPerLine() // 4, 4)
        )
        return padded[:, :width, [2, 1, 0]].copy()
