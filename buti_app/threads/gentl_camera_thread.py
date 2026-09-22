import logging
import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from cameras.controls import CameraController
from cameras.gentl_backend import GenTLSession, GenTLControls, SUPPORTED_FORMATS
from utils.config import DEFAULT_FPS

log = logging.getLogger(__name__)


def copy_gentl_frame(component):
    name = component.data_format
    if name not in SUPPORTED_FORMATS:
        raise RuntimeError(f"Unsupported GenTL format {name}; select Mono8 or RGB8.")
    color = name.startswith(("RGB", "BGR"))
    shape = (component.height, component.width, 3) if color else (component.height, component.width)
    data = np.asarray(component.data)
    if data.size != int(np.prod(shape)):
        # Some producers expose row padding in Harvester's expanded array.
        channels = 3 if color else 1
        row_samples = component.width * channels + int(getattr(component, "x_padding", 0)) // data.itemsize
        data = data.reshape(-1, row_samples)[:component.height, :component.width * channels]
    data = data.reshape(shape)
    if name.startswith("Mono") and name != "Mono8":
        # Fixed bit-depth scaling, never per-frame min/max normalization.
        data = np.right_shift(data, int(name[4:]) - 8)
    if name.startswith("BGR"):
        data = data[:, :, ::-1]
    array = np.array(data, dtype=np.uint8, copy=True, order="C")
    fmt = QImage.Format_RGB888 if color else QImage.Format_Grayscale8
    image = QImage(array.data, component.width, component.height, array.strides[0], fmt).copy()
    return image, array


class GenTLCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None, *, sdk, genapi):
        super().__init__(parent)
        self.sdk, self.genapi = sdk, genapi
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
            with GenTLSession(self.sdk, self._device_info["producer"]) as session:
                session.open(self._device_info["id"])
                adapter = GenTLControls(session, self.genapi)
                try:
                    adapter.configure(self._resolution, DEFAULT_FPS)
                    session.acquirer.start()
                    session.acquiring = True
                    self.controller.open(adapter)
                    self.grabber_ready.emit()
                    last_frame = time.monotonic()
                    while not self._stop_requested:
                        self.controller.service(adapter)
                        buffer = session.acquirer.try_fetch(timeout=0.5)
                        if buffer is None:
                            if time.monotonic() - last_frame > 5:
                                raise RuntimeError("No frames received for five seconds; check camera connection and trigger settings.")
                            continue
                        buffers = buffer if isinstance(buffer, list) else [buffer]
                        components = None
                        try:
                            if len(buffers) != 1:
                                raise RuntimeError("GenTL multi-stream payloads are not supported.")
                            components = buffers[0].payload.components
                            if len(components) != 1:
                                raise RuntimeError("GenTL multi-component payloads are not supported.")
                            image, array = copy_gentl_frame(components[0])
                        finally:
                            # Returning native buffers is required before stop/destroy.
                            for fetched in buffers:
                                if fetched is not None:
                                    fetched.queue()
                            components = None
                            del fetched
                            del buffers
                            del buffer
                        last_frame = time.monotonic()
                        self.frame_ready.emit(image, array)
                finally:
                    self.controller.close()
                    del adapter
        except Exception as exc:
            log.error("GenTL camera failed: %s", exc)
            if not self._stop_requested:
                self.error.emit(f"GenTL camera failed: {exc}\nCheck the SDK's GenTL producer and camera connection.", "gentl-acquisition")
        finally:
            self.controller.close()
