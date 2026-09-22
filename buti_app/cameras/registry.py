import importlib
from importlib.metadata import entry_points
import logging
from .ic4_backend import IC4Backend
from .opencv_backend import OpenCVBackend
from .spinnaker_backend import SpinnakerBackend
from .gentl_backend import GenTLBackend
from .runtime import configure_dll_paths

log = logging.getLogger(__name__)


class CameraRegistry:
    """Built-in and installed camera adapters share the same UI contract."""
    backend_types = (IC4Backend, SpinnakerBackend, GenTLBackend, OpenCVBackend)

    def __init__(self, backend_filter="auto", importer=importlib.import_module, plugin_entries=None):
        configure_dll_paths()
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
        # SDK adapter packages opt in by registering this entry-point group.
        # They run with application privileges, like any installed Python package.
        try:
            entries = entry_points(group="burst.camera_backends") if plugin_entries is None else plugin_entries
            for entry in entries:
                if not selected.intersection({"", "auto", "all", entry.name}):
                    continue
                try:
                    if entry.name in self.backends or entry.name in {b.key for b in self.backend_types}:
                        raise ValueError("adapter key conflicts with a built-in backend")
                    backend = entry.load()()
                    if backend.key != entry.name:
                        raise ValueError("adapter key must match its entry-point name")
                    self.backends[entry.name] = backend
                    log.info("Camera backend %s: available (installed adapter)", entry.name)
                except Exception as exc:
                    log.warning("Camera adapter %s unavailable: %s", entry.name, exc)
        except Exception as exc:
            log.warning("Installed camera adapter discovery failed: %s", exc)

    def discover_cameras(self):
        devices = []
        identities = set()
        ordered = sorted(self.backends.items(), key=lambda item: {"gentl": 1, "opencv": 2}.get(item[0], 0))
        for key, backend in ordered:
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
