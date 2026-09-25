"""Plugin frames use the same controller, timing signals and recorder as IC4."""
import logging
import time
import numpy as np
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QImage

from cameras.controls import CameraController
from cameras.frame_data import FrameData
from cameras.plugin_process import PluginClient, PluginControls, PluginCancelled
from cameras.timing_thread import TimingCameraThread

log = logging.getLogger(__name__)


def decode_frame(payload):
    shape, dtype = tuple(payload["shape"]), np.dtype(payload["dtype"])
    mono = len(shape) == 2 and dtype in (np.dtype("uint8"), np.dtype("uint16"))
    rgb = len(shape) == 3 and shape[2] == 3 and dtype == np.dtype("uint8")
    if not (mono or rgb) or any(type(n) is not int or n <= 0 for n in shape):
        raise ValueError("Unsupported camera plugin frame layout")
    if len(payload["pixels"]) != int(np.prod(shape)) * dtype.itemsize:
        raise ValueError("Incomplete camera plugin frame")
    bits = payload["bit_depth"]
    if type(bits) is not int or not 1 <= bits <= dtype.itemsize * 8 or (rgb and bits != 8):
        raise ValueError("Invalid camera plugin bit depth")
    pixels = np.frombuffer(payload["pixels"], dtype=dtype).reshape(shape)
    display = np.ascontiguousarray(np.clip(pixels >> max(0, bits - 8), 0, 255), dtype=np.uint8)
    image = QImage(display.data, shape[1], shape[0], display.strides[0],
                   QImage.Format_Grayscale8 if mono else QImage.Format_RGB888).copy()
    frame = FrameData.copy(pixels, pixel_format=f"Mono{bits}" if mono else "RGB8",
                           camera_frame_id=payload["camera_frame_id"], metadata=payload["metadata"])
    return image, frame


class PluginCameraThread(TimingCameraThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, manifest, device_id, parent=None, client_factory=PluginClient):
        super().__init__(parent)
        self.manifest, self.device_id = manifest, device_id
        self.client_factory = client_factory
        self.controller = CameraController()
        self._stop_requested = False
        self._resolution = None

    def set_resolution(self, resolution):
        self._resolution = resolution if resolution and resolution[0] and resolution[1] else None

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            with self.client_factory(self.manifest, cancelled=lambda: self._stop_requested) as client:
                client.request("open", self.device_id, self._resolution)
                adapter = PluginControls(client, self.manifest)
                source = ""

                def switch(requested):
                    nonlocal source
                    updated = client.request("timing", requested)
                    source = requested
                    self.trigger_input = updated["trigger_input"]
                    log.info("Plugin %s timing: %s", self.manifest.id, updated["trigger_configuration"] or "preview")
                    return updated["trigger_configuration"]

                initial = getattr(self, "hardware_trigger_source", "")
                if initial:
                    self.trigger_configuration = switch(initial)
                self.controller.open(adapter)
                if self._stop_requested:
                    return
                self.grabber_ready.emit()
                last_frame = time.monotonic()
                while not self._stop_requested:
                    self.controller.service(adapter)
                    if self.service_timing(switch):
                        last_frame = time.monotonic()
                    payload = client.request("next")
                    if payload is not None:
                        image, frame = decode_frame(payload)
                        self.frame_ready.emit(image, frame)
                        last_frame = time.monotonic()
                    elif not source and time.monotonic() - last_frame > 5:
                        raise RuntimeError("No preview frames for five seconds. Check exposure, free-running acquisition and the plugin's SDK setup.")
                    else:
                        self.msleep(2)
        except PluginCancelled:
            pass
        except Exception as exc:
            log.exception("Camera plugin acquisition failed")
            if not self._stop_requested:
                self.error.emit(str(exc), "camera-plugin")
        finally:
            self.controller.close()
