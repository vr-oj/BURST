"""Real Micro-Manager acquisition; the historical OpenCV aliases are separate."""
import logging
import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from cameras.controls import CameraController
from cameras.micro_manager_backend import MicroManagerSession, MicroManagerControls

log = logging.getLogger(__name__)


def copy_mm_frame(data, components, bit_depth):
    data = np.asarray(data)
    if components == 1 and data.ndim == 2 and data.dtype in (np.dtype("uint8"), np.dtype("uint16")):
        if not 1 <= bit_depth <= data.dtype.itemsize * 8:
            raise RuntimeError("Camera reports an invalid monochrome bit depth.")
        scaled = np.clip(np.right_shift(data, max(0, bit_depth - 8)), 0, 255)
        array = np.array(scaled, dtype=np.uint8, order="C", copy=True)
        fmt = QImage.Format_Grayscale8
    elif components == 4 and data.dtype == np.dtype("uint32") and data.ndim == 2:
        # MMCore packed RGB32 uses 0x00RRGGBB; never reinterpret native endian bytes.
        array = np.stack(((data >> 16) & 255, (data >> 8) & 255, data & 255), axis=-1).astype(np.uint8)
        fmt = QImage.Format_RGB888
    else:
        raise RuntimeError(f"Unsupported Micro-Manager image layout: {data.dtype}, {data.shape}, {components} components. Select 8/16-bit mono or 32-bit RGB.")
    height, width = array.shape[:2]
    return QImage(array.data, width, height, array.strides[0], fmt).copy(), array


class MMCoreCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None, *, sdk, profile):
        super().__init__(parent)
        self.sdk, self.profile = sdk, dict(profile)
        self.controller = CameraController()
        self._stop_requested = False

    def set_resolution(self, resolution):
        # Geometry and pixel type are defined by the configuration/adapter.
        pass

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            with MicroManagerSession(self.sdk, self.profile) as session:
                adapter = MicroManagerControls(session)
                try:
                    # Preserve adapter-specific trigger settings from the configuration.
                    # Request 10 Hz only where the adapter names the SFNC rate property.
                    controls = adapter.read_controls()
                    fps = controls.get("mm:AcquisitionFrameRate")
                    if fps and fps.writable:
                        try:
                            adapter.set_value("mm:AcquisitionFrameRate", "10")
                        except Exception as exc:
                            log.warning("Micro-Manager could not request 10 FPS: %s", exc)
                    if self._stop_requested:
                        return
                    session.start()
                    self.controller.open(adapter)
                    self.grabber_ready.emit()
                    last_frame = time.monotonic()
                    while not self._stop_requested:
                        self.controller.service(adapter)
                        if session.core.isBufferOverflowed():
                            raise RuntimeError("Micro-Manager image buffer overflow. Reduce acquisition rate or resolution.")
                        if session.core.getRemainingImageCount():
                            components = session.core.getNumberOfComponents()
                            bit_depth = session.core.getImageBitDepth()
                            frame = np.array(session.core.popNextImage(), copy=True)
                            image, array = copy_mm_frame(frame, components, bit_depth)
                            last_frame = time.monotonic()
                            self.frame_ready.emit(image, array)
                        else:
                            if not session.core.isSequenceRunning():
                                raise RuntimeError("The camera stopped sequence acquisition.")
                            if time.monotonic() - last_frame > 5:
                                raise RuntimeError("No images for five seconds. Check exposure, connection and configured trigger source. Use internal/free-running triggering for preview.")
                            self.msleep(5)
                finally:
                    self.controller.close()
        except Exception as exc:
            log.exception("Micro-Manager acquisition failed")
            if not self._stop_requested:
                self.error.emit(f"Micro-Manager: {exc}\nClose other camera applications and check the configuration, vendor drivers, and adapter/API compatibility.", "micromanager-acquisition")
        finally:
            self.controller.close()
