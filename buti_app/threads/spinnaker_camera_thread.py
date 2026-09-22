import importlib
import logging
import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from cameras.controls import CameraController
from cameras.spinnaker_backend import SpinnakerSession, SpinnakerControls
from utils.config import DEFAULT_FPS

log = logging.getLogger(__name__)


def copy_spinnaker_frame(sdk, image, processor):
    """Detach both payloads before releasing native images; use fixed SDK conversion."""
    converted = None
    try:
        name = image.GetPixelFormatName()
        color = any(token in name.lower() for token in ("bayer", "rgb", "bgr", "yuv", "ycbcr"))
        target = sdk.PixelFormat_RGB8 if color else sdk.PixelFormat_Mono8
        source = image
        if name != ("RGB8" if color else "Mono8"):
            converted = processor.Convert(image, target)
            source = converted
        array = np.array(source.GetNDArray(), dtype=np.uint8, copy=True, order="C")
        height, width = array.shape[:2]
        fmt = QImage.Format_RGB888 if color else QImage.Format_Grayscale8
        qimage = QImage(array.data, width, height, array.strides[0], fmt).copy()
        return qimage, array
    finally:
        if converted is not None:
            converted.Release()


class SpinnakerCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None, *, sdk=None):
        super().__init__(parent)
        self.sdk = sdk
        self.controller = CameraController()
        self._device_info = None
        self._resolution = None
        self._stop_requested = False

    def set_device_info(self, device):
        self._device_info = device

    def set_resolution(self, resolution):
        self._resolution = resolution

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            sdk = self.sdk or importlib.import_module("PySpin")
            with SpinnakerSession(sdk) as session:
                session.open(self._device_info)
                adapter = SpinnakerControls(session)
                adapter.configure(self._resolution, DEFAULT_FPS)
                processor = sdk.ImageProcessor()
                processor.SetColorProcessing(sdk.SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR)
                try:
                    session.camera.BeginAcquisition()
                    session.acquiring = True
                    self.controller.open(adapter)
                    self.grabber_ready.emit()
                    last_frame = time.monotonic()
                    while not self._stop_requested:
                        self.controller.service(adapter)
                        try:
                            image = session.camera.GetNextImage(500)
                        except Exception as exc:
                            code = getattr(exc, "errorcode", None)
                            if self._stop_requested:
                                break
                            if code == getattr(sdk, "SPINNAKER_ERR_TIMEOUT", -1011) and time.monotonic() - last_frame < 5:
                                continue
                            raise
                        try:
                            if image.IsIncomplete():
                                if time.monotonic() - last_frame > 5:
                                    raise RuntimeError("Camera is delivering incomplete images; check the connection/bandwidth.")
                                continue
                            qimage, array = copy_spinnaker_frame(sdk, image, processor)
                        finally:
                            image.Release()
                            del image
                        last_frame = time.monotonic()
                        self.frame_ready.emit(qimage, array)
                finally:
                    self.controller.close()
                    del processor
                    del adapter
        except Exception as exc:
            log.error("Spinnaker camera failed: %s", exc)
            if not self._stop_requested:
                self.error.emit(
                    f"Spinnaker camera failed: {exc}\nCheck that the camera is connected and not in use, "
                    "and that PySpin matches the installed Spinnaker SDK/runtime.", "spinnaker-acquisition")
        finally:
            self.controller.close()
