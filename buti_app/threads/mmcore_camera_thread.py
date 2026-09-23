"""Real Micro-Manager acquisition; the historical OpenCV aliases are separate."""
import logging
import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from cameras.controls import CameraController
from cameras.frame_data import FrameData
from cameras.timing_thread import TimingCameraThread
from cameras.micro_manager_process import MicroManagerClient, RemoteMicroManagerControls, MicroManagerCancelled

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


class MMCoreCameraThread(TimingCameraThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None, *, sdk=None, profile, client_factory=MicroManagerClient):
        super().__init__(parent)
        self.sdk, self.profile = sdk, dict(profile)
        self.client_factory = client_factory
        self.controller = CameraController()
        self._stop_requested = False

    def set_resolution(self, resolution):
        # Geometry and pixel type are defined by the configuration/adapter.
        pass

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            log.info("Starting isolated Micro-Manager camera: %s", self.profile)
            with self.client_factory(cancelled=lambda: self._stop_requested) as client:
                source = getattr(self, "hardware_trigger_source", "")
                snapshot = client.request("open", self.profile, source)
                self.trigger_configuration = snapshot.get("trigger_configuration", {})
                adapter = RemoteMicroManagerControls(client, snapshot)
                try:
                    if self._stop_requested:
                        return
                    self.controller.open(adapter)
                    self.grabber_ready.emit()
                    last_frame = time.monotonic()

                    def switch_timing(requested):
                        nonlocal source
                        updated = client.request("timing", requested)
                        source = requested
                        log.info("Micro-Manager acquisition timing: %s", updated["trigger_configuration"] or "preview")
                        return updated["trigger_configuration"]

                    while not self._stop_requested:
                        self.controller.service(adapter)
                        if self.service_timing(switch_timing):
                            last_frame = time.monotonic()
                        payload = client.request("next", timeout=10)
                        if payload is not None:
                            frame, components, bit_depth = payload
                            image, array = copy_mm_frame(frame, components, bit_depth)
                            last_frame = time.monotonic()
                            self.frame_ready.emit(image, FrameData.copy(frame if components == 1 else array,
                                pixel_format=f"Mono{bit_depth}" if components == 1 else "RGB8"))
                        else:
                            if not source and time.monotonic() - last_frame > 5:
                                raise RuntimeError("No images for five seconds. Check exposure, connection and configured trigger source. Use internal/free-running triggering for preview.")
                            self.msleep(5)
                finally:
                    self.controller.close()
        except MicroManagerCancelled:
            pass
        except Exception as exc:
            log.exception("Micro-Manager acquisition failed")
            if not self._stop_requested:
                self.error.emit(f"Micro-Manager: {exc}\nClose other camera applications and check the configuration, vendor drivers, and adapter/API compatibility.", "micromanager-acquisition")
        finally:
            self.controller.close()
