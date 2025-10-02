# buti_app/recording_manager.py

import os
import time
import csv
import json
import shutil
import numpy as np
from collections import deque
import tifffile
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QImage
import logging

from utils.config import MIN_FREE_SPACE_GB

log = logging.getLogger(__name__)

class RecordingManager(QObject):
    """Manage synchronized writing of force data and camera frames."""

    # Emitted when :func:`start_recording` has finished its setup and the worker
    # is ready to receive the first BUTI Arduino Box tick.  The main window can listen for
    # this signal to safely start the hardware acquisition.
    ready_for_acquisition = pyqtSignal()
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir

        # Paths (populated in ``start_recording``)
        self._csv_path = None
        self._tiff_path = None

        # File handles & writers
        self.csv_file = None
        self.csv_writer = None
        self.tif_writer = None

        # Internal info
        self._first_frame_shape = None

        # Recording flags
        self.is_recording = False
        self._got_first_sample = False
        self._stop_requested = False

        # Counters for syncing
        self._frame_counter = 0
        self._last_device_time = 0
        self._frames_written = 0
        self._samples_written = 0
        self._pending_samples = deque()


    @pyqtSlot()
    def start_recording(self):
        """Prepare file paths and wait for the first force sample."""
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"recording_{timestamp}"

        os.makedirs(self.output_dir, exist_ok=True)
        
        # ─── Verify free disk space before recording ──────────────────────────
        total, used, free = shutil.disk_usage(self.output_dir)
        if free < MIN_FREE_SPACE_GB * 1024 ** 3:
            gb_free = free / 1024 ** 3
            log.error(
                f"Insufficient disk space: {gb_free:.2f} GB available, {MIN_FREE_SPACE_GB} GB required."
            )
            self.error_occurred.emit("Not enough disk space for recording.")
            self.ready_for_acquisition.emit()
            return
        
        self._csv_path = os.path.join(self.output_dir, f"{base_name}_force.csv")
        self._tiff_path = os.path.join(self.output_dir, f"{base_name}_video.tif")
        self._first_frame_shape = None

        self.is_recording = True
        self._got_first_sample = False
        self._frame_counter = 0
        self._pending_samples.clear()
        self._last_device_time = 0
        self._stop_requested = False
        self._frames_written = 0
        self._samples_written = 0
        self._pending_samples.clear()

        log.info(
            f"Ready to record →\n  CSV will be: {self._csv_path}\n  TIFF will be: {self._tiff_path}"
        )
        log.info("Waiting for the first BUTI Arduino Box tick to open files...")
        # Notify the GUI that the worker thread finished setup and the files
        # paths have been prepared.  The application can now start the BUTI Arduino Box
        # so the first sample will create the CSV/TIFF files.
        self.ready_for_acquisition.emit()

    @pyqtSlot(float, int, float, int, float)
    def append_force(
        self,
        time_s: float,
        frame_idx: int,
        distance: float,
        cycle: int,
        force: float,
    ):
        """Handle a sample from the serial thread."""
        if not self.is_recording:
            return

        if not self._got_first_sample:
            self._got_first_sample = True
            try:
                self.csv_file = open(self._csv_path, "w", newline="")
                self.csv_writer = csv.writer(self.csv_file)
                self.csv_writer.writerow(
                    ["time_s", "frame_index", "distance", "cycle", "force"]
                )
            except Exception as e:
                log.error(f"Failed to open CSV: {e}")
                self.error_occurred.emit(f"Failed to open CSV file: {e}")
                self.is_recording = False
                return
            try:
                self.tif_writer = tifffile.TiffWriter(self._tiff_path, bigtiff=True)
            except Exception as e:
                log.error(f"Failed to open TIFF: {e}")
                self.error_occurred.emit(f"Failed to open TIFF file: {e}")
                if self.csv_file:
                    self.csv_file.close()
                    self.csv_file = None
                    self.csv_writer = None
                self.is_recording = False
                return
            log.info(
                f"Recording truly started →\n  CSV: {self._csv_path}\n  TIFF: {self._tiff_path}"
            )

        if self.csv_writer:
            try:
                self.csv_writer.writerow([time_s, frame_idx, distance, cycle, force])
                self._last_device_time = time_s
                self._samples_written += 1
                # Keep full sample so TIFF metadata mirrors the CSV row
                self._pending_samples.append(
                    (time_s, frame_idx, distance, cycle, force)
                )

            except Exception as e:
                log.error(
                    "Error writing CSV row (%s, %s, %s, %s, %s): %s",
                    time_s,
                    frame_idx,
                    distance,
                    cycle,
                    force,
                    e,
                )
                self.error_occurred.emit(f"Error writing CSV: {e}")
        self._check_stop_condition()

    @pyqtSlot(QImage, object)
    def append_frame(self, qimage, raw):
        """Handle a camera frame from the camera thread."""
        if not self.is_recording or not self._got_first_sample:
            return

        if not self._pending_samples:
            return  # No matching force sample yet

        if self.tif_writer:
            try:
                arr = self._qimage_to_numpy(qimage)
                if self._first_frame_shape is None:
                    self._first_frame_shape = arr.shape
                sample = self._pending_samples.popleft()
                (
                    time_s,
                    frame_idx,
                    distance,
                    cycle,
                    force,
                ) = sample
                metadata = {
                    "time_s": time_s,
                    "frameIdx": frame_idx,
                    "distance": distance,
                    "cycle": cycle,
                    "force": force,
                }
                self.tif_writer.write(arr, description=json.dumps(metadata))
                self._frame_counter += 1
                self._frames_written += 1
                self._last_device_time = time_s

            except Exception as e:
                failed_idx = max(0, self._frame_counter)
                log.error(
                    f"Error writing TIFF page for frame {failed_idx}: {e}"
                )
                self.error_occurred.emit(f"Error writing video frame: {e}")
        self._check_stop_condition()

    @pyqtSlot()
    def stop_recording(self):
        """Close files and reset state."""
        if not self.is_recording:
            return

        self.is_recording = False

        try:
            if self.tif_writer:
                self.tif_writer.close()
                self.tif_writer = None
        except Exception as e:
            log.error(f"Error closing TIFF: {e}")
            self.error_occurred.emit(f"Error closing TIFF: {e}")

        try:
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
        except Exception as e:
            log.error(f"Error closing CSV: {e}")
            self.error_occurred.emit(f"Error closing CSV: {e}")

        # Optional overlays, logs, and summary are no longer generated

        self._got_first_sample = False
        self._frame_counter = 0

        log.info("Recording stopped and files closed.")
        self.finished.emit()

    @pyqtSlot()
    def request_stop(self):
        """Signal that recording should stop after the next synced frame."""
        if not self.is_recording:
            return
        self._stop_requested = True
        self._check_stop_condition()

    def _check_stop_condition(self):
        """Close files when a stop was requested and counts match."""
        if (
            self._stop_requested
            and self._frames_written == self._samples_written
            and not self._pending_samples
        ):

            self.stop_recording()

    def _qimage_to_numpy(self, qimage):
        """Convert a ``QImage`` to a ``numpy.ndarray``.

        If the image is already 8‑bit grayscale, the raw bytes are read
        directly into a ``(H, W)`` ``uint8`` array.  Otherwise the image is
        converted to ARGB32 and the returned array has shape ``(H, W, 3)`` in
        RGB order.
        """

        fmt = qimage.format()
        if fmt in (QImage.Format_Grayscale8, QImage.Format_Indexed8):
            w, h = qimage.width(), qimage.height()
            ptr = qimage.bits()
            ptr.setsize(qimage.byteCount())
            arr = np.frombuffer(ptr, np.uint8).reshape((h, w))
            return arr

        qimg = qimage.convertToFormat(QImage.Format_ARGB32)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 4))
        return arr[:, :, [2, 1, 0]]
