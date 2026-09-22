import importlib
import logging
from .ic4_backend import IC4Backend
from .opencv_backend import OpenCVBackend
from .spinnaker_backend import SpinnakerBackend

log = logging.getLogger(__name__)


class CameraRegistry:
    """Extend backend_types to register another transport (for example GenTL)."""
    backend_types = (IC4Backend, SpinnakerBackend, OpenCVBackend)

    def __init__(self, backend_filter="auto", importer=importlib.import_module):
        self.backends = {}
        self.unavailable = {}
        selected = {s.strip() for s in backend_filter.lower().split(",")}
        for backend_type in self.backend_types:
            key = backend_type.key
            if not selected.intersection({"", "auto", "all", key}):
                continue
            try:
                sdk = importer(backend_type.module_name)
                self.backends[key] = backend_type(sdk)
                log.info("Camera backend %s: available", key)
            except Exception as exc:
                self.unavailable[key] = str(exc)
                log.info("Camera backend %s: unavailable (%s)", key, exc)

    def discover_cameras(self):
        devices = []
        identities = set()
        for key, backend in self.backends.items():
            try:
                for device in backend.discover():
                    if device.physical_id and device.physical_id in identities:
                        log.info("Skipping duplicate camera %s", device.display_name)
                        continue
                    if device.physical_id:
                        identities.add(device.physical_id)
                    devices.append(device)
                    log.info("Discovered %s camera: %s (id=%s, serial=%s)",
                             key, device.display_name, device.id, device.serial)
            except Exception as exc:
                log.warning("Camera backend %s discovery failed: %s", key, exc)
        if any(d.backend == "opencv" for d in devices) and any(d.backend != "opencv" for d in devices):
            log.info("Generic camera entries may duplicate vendor SDK devices. OpenCV exposes no "
                     "stable hardware identity; keeping these candidates to avoid hiding distinct cameras.")
        return devices

    def list_modes(self, device):
        try:
            return self.backends[device.backend].list_modes(device)
        except Exception as exc:
            log.warning("Could not read camera modes for %s: %s", device.display_name, exc)
            return []

    def get_thread(self, device, parent=None):
        return self.backends[device.backend].create_thread(device, parent)

    def close(self):
        for key, backend in self.backends.items():
            try:
                backend.close()
            except Exception as exc:
                log.warning("Camera backend %s cleanup failed: %s", key, exc)
