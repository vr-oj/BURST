import importlib
import importlib.util
import logging
from .ic4_backend import IC4Backend
from .micro_manager_backend import MicroManagerBackend
from .runtime import configure_dll_paths

log = logging.getLogger(__name__)


class CameraRegistry:
    """Native IC4 first; other cameras use installed Micro-Manager adapters."""
    backend_types = (IC4Backend, MicroManagerBackend)
    default_backends = frozenset({"ic4", "micromanager"})

    def __init__(self, backend_filter="auto", importer=importlib.import_module):
        configure_dll_paths()
        self.backends = {}
        self.unavailable = {}
        selected = {s.strip() for s in backend_filter.lower().split(",")}
        if selected.intersection({"", "auto"}):
            selected = (selected - {"", "auto"}) | self.default_backends
        for backend_type in self.backend_types:
            key = backend_type.key
            if not selected.intersection({"all", key}):
                continue
            try:
                if backend_type is MicroManagerBackend and importer is importlib.import_module:
                    # Do not load MMCore's C++ runtime beside Qt/vendor SDKs.
                    if importlib.util.find_spec("pymmcore") is None:
                        raise ImportError("pymmcore is not included in this BURST installation")
                    sdk = True  # Availability marker; the helper performs the import.
                else:
                    sdk = importer(backend_type.module_name)
                self.backends[key] = backend_type(sdk)
                log.info("Camera backend %s: available", key)
            except Exception as exc:
                self.unavailable[key] = str(exc)
                log.info("Camera backend %s: unavailable (%s)", key, exc)

    def set_micro_manager_profiles(self, profiles):
        backend = self.backends.get("micromanager")
        if backend is not None:
            backend.profiles = [dict(p) for p in profiles if isinstance(p, dict)] if isinstance(profiles, list) else []

    def discover_cameras(self):
        devices = []
        identities = set()
        for key, backend in self.backends.items():
            try:
                for device in backend.discover():
                    # Explicitly saved MM profiles remain selectable as an
                    # alternative route to a camera also offered by its SDK.
                    if key != "micromanager" and device.physical_id and device.physical_id in identities:
                        log.info("Skipping duplicate camera %s", device.display_name)
                        continue
                    if key != "micromanager" and device.physical_id:
                        identities.add(device.physical_id)
                    devices.append(device)
                    log.info("Discovered %s camera: %s (id=%s, serial=%s)",
                             key, device.display_name, device.id, device.serial)
            except Exception as exc:
                log.warning("Camera backend %s discovery failed: %s", key, exc)
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
