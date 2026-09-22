import logging
import os
import sys
from .models import CameraDeviceInfo, CameraMode

log = logging.getLogger(__name__)


def open_capture(cv2, index):
    """Try DirectShow then Media Foundation on Windows, releasing failed handles."""
    apis = [cv2.CAP_DSHOW, cv2.CAP_MSMF] if sys.platform == "win32" else [cv2.CAP_ANY]
    for api in apis:
        capture = None
        try:
            capture = cv2.VideoCapture(index, api)
            if capture is not None and capture.isOpened():
                return capture
        except Exception as exc:
            log.debug("OpenCV index %s API %s: %s", index, api, exc)
        if capture is not None:
            capture.release()
    return None


class OpenCVBackend:
    key = "opencv"
    module_name = "cv2"

    def __init__(self, sdk):
        self.sdk = sdk

    def discover(self):
        from threads.micromanager_camera_thread import DevCameraSource
        index_env = os.environ.get("BURST_CAMERA_INDEX") or os.environ.get("BUTI_CAMERA_INDEX")
        try:
            indexes = [max(0, int(index_env))] if index_env is not None else range(3)
        except ValueError:
            log.warning("Invalid camera index %r; probing indices 0–2", index_env)
            indexes = range(3)
        devices = []
        for index in indexes:
            capture = open_capture(self.sdk, index)
            if capture is None:
                continue
            try:
                devices.append(CameraDeviceInfo(self.key, str(index),
                    f"USB Camera #{index} — Generic USB / OpenCV", native_info=DevCameraSource("opencv", index)))
            finally:
                capture.release()
        return devices

    def list_modes(self, device):
        return [CameraMode(0, 0, "RGB8"), CameraMode(640, 480, "Mono8"),
                CameraMode(960, 720, "Mono8"), CameraMode(1280, 720, "RGB8")]

    def create_thread(self, device, parent=None):
        from threads.micromanager_camera_thread import DevCameraThread
        thread = DevCameraThread(parent)
        thread.set_device_info(device.native_info)
        return thread

    def close(self):
        pass
