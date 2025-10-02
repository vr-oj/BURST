"""Developer-friendly camera thread used when IC4 is unavailable.

Provides an OpenCV-based implementation so the rest of the UI can stay
untouched while working on macOS or in a headless development environment.

The goal is to mirror the public surface of ``SDKCameraThread`` closely enough so
the rest of the UI can stay untouched while working on macOS or in a headless
development environment.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass


from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from utils.config import DEFAULT_FPS

log = logging.getLogger(__name__)

try:  # Optional dependency, only needed for the OpenCV backend
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - OpenCV is optional
    cv2 = None


@dataclass
class DevCameraSource:
    backend: str  # ``opencv`` only
    index: int = 0  # OpenCV device index
    name: str = "OpenCV Camera"


class DevCameraThread(QThread):
    """Drop-in replacement for :class:`SDKCameraThread` when IC4 is absent."""

    grabber_ready = pyqtSignal()  # Kept for API parity; never emitted here.
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self._resolution = None  # (width, height, pixel_format)
        self._source: DevCameraSource = DevCameraSource(backend="opencv")
        self._fps = DEFAULT_FPS

        fps_env = os.environ.get("BURST_CAMERA_FPS") or os.environ.get("BUTI_CAMERA_FPS")
        if fps_env:
            try:
                fps_value = float(fps_env)
                if fps_value > 0:
                    self._fps = fps_value
            except ValueError:
                log.warning(
                    "Invalid BURST_CAMERA_FPS value %r; using default %s fps.",
                    fps_env,
                    self._fps,
                )

        # Attributes mirrored from SDKCameraThread for compatibility
        self.grabber = None

        self._capture = None
        self._frame_counter = 0

    # ------------------------------------------------------------------
    # Interface expected by MainWindow
    # ------------------------------------------------------------------
    def set_device_info(self, dev_info):
        if isinstance(dev_info, DevCameraSource):
            self._source = dev_info
        elif isinstance(dev_info, dict):
            backend = dev_info.get("backend", "opencv")
            index = dev_info.get("index", 0)
            name = dev_info.get("name", "OpenCV Camera")
            self._source = DevCameraSource(backend=backend, index=index, name=name)
        else:
            log.warning(
                "DevCameraThread received unexpected device info %r; defaulting to OpenCV backend.",
                dev_info,
            )
            self._source = DevCameraSource(backend="opencv")

    def set_resolution(self, resolution_tuple):
        self._resolution = resolution_tuple

    def stop(self):
        self._stop_requested = True

    # ------------------------------------------------------------------
    # QThread implementation
    # ------------------------------------------------------------------
    def run(self):
        self._stop_requested = False
        backend = self._source.backend.lower()

        if backend != "opencv":
            log.warning(
                "DevCameraThread received unsupported backend %r; defaulting to OpenCV.",
                backend,
            )
            self._source.backend = "opencv"
            backend = "opencv"

        if cv2 is None:
            self.error.emit(
                "OpenCV backend requested but opencv-python is not installed.",
                "dev-camera-opencv-missing",
            )
            return
        self._run_opencv_backend()

    # ------------------------------------------------------------------
    # Backend helpers
    # ------------------------------------------------------------------
    def _run_opencv_backend(self):
        assert cv2 is not None  # Guarded by caller

        index = self._source.index
        capture = cv2.VideoCapture(index)
        if not capture or not capture.isOpened():
            self.error.emit(
                f"Unable to open OpenCV VideoCapture index {index}.",
                "dev-camera-opencv-open",
            )
            return
        self._capture = capture
        width, height, _ = self._resolution or (1280, 720, "RGB8")
        target_width = int(width)
        target_height = int(height)

        if target_width > 0 and target_height > 0:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, target_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, target_height)
        else:
            target_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            target_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480

        capture.set(cv2.CAP_PROP_FPS, float(self._fps))

        log.info(
            "DevCameraThread using OpenCV backend (device=%s, resolution=%sx%s)",
            index,
            target_width,
            target_height,
        )

        sleep_ms = max(1, int(1000 / max(self._fps, 1)))

        try:
            while not self._stop_requested:
                ok, frame = capture.read()
                if not ok:
                    self.error.emit("Failed to read frame from OpenCV camera.", "dev-camera-opencv-read")
                    break

                if frame is None:
                    continue

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
                self.frame_ready.emit(qimg, rgb)
                self._frame_counter += 1
                self.msleep(sleep_ms)
        finally:
            capture.release()
            self._capture = None

        log.info("DevCameraThread OpenCV backend stopped after %d frames.", self._frame_counter)

# Backwards compatibility export expected by ``threads.__init__``
MicroManagerCameraThread = DevCameraThread








