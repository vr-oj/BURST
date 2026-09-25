"""Read plugin manifests without importing any lab/vendor code into BURST."""
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import time

from .models import CameraDeviceInfo, CameraMode

log = logging.getLogger(__name__)


def plugin_directory():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "BURST" / "CameraPlugins"


def plugin_roots():
    # The override also lets tests and lab deployments use an isolated location.
    override = os.environ.get("BURST_CAMERA_PLUGIN_PATH")
    return [Path(p) for p in override.split(os.pathsep) if p] if override else [plugin_directory()]


@dataclass(frozen=True)
class PluginManifest:
    path: Path
    id: str
    name: str
    version: str
    python: Path

    @classmethod
    def read(cls, path):
        path = Path(path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("api_version") != 1:
            raise ValueError("Requires camera plugin API 1")
        identifier = data.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", identifier):
            raise ValueError("Plugin id must be 3–64 lowercase letters, digits or underscores")
        if identifier in {"ic4", "micromanager", "auto", "all"}:
            raise ValueError("Plugin id is reserved for a built-in connection")
        for key in ("name", "version", "python", "entry_point"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"Missing plugin {key}")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", data["entry_point"]):
            raise ValueError("entry_point must be module:ClassName")
        python = (path.parent / data["python"]).resolve()
        if not python.is_file():
            raise ValueError(f"Plugin Python environment not found: {python}. Run the lab's plugin setup first.")
        directories = data.get("dll_directories", [])
        if not isinstance(directories, list) or any(not isinstance(p, str) for p in directories):
            raise ValueError("dll_directories must be a list of paths")
        for directory in directories:
            if not (path.parent / directory).is_dir():
                raise ValueError(f"SDK DLL directory not found: {directory}")
        return cls(path, identifier, data["name"], data["version"], python)


def load_plugins(roots=None):
    manifests, errors, duplicates = {}, {}, set()
    for root in plugin_roots() if roots is None else roots:
        for path in sorted(Path(root).glob("*/plugin.json")):
            try:
                # Disabled plugins never execute (and need not have a runtime).
                if json.loads(path.read_text(encoding="utf-8")).get("enabled", True) is False:
                    continue
                manifest = PluginManifest.read(path)
                if manifest.id in manifests or manifest.id in duplicates:
                    manifests.pop(manifest.id, None)
                    duplicates.add(manifest.id)
                    raise ValueError(f"Duplicate plugin id '{manifest.id}'; neither copy will load")
                manifests[manifest.id] = manifest
            except Exception as exc:
                errors[str(path)] = str(exc)
                log.warning("Camera plugin %s unavailable: %s", path, exc)
    return {"plugin:" + key: PluginBackend(value) for key, value in manifests.items()}, errors


class PluginBackend:
    def __init__(self, manifest):
        self.manifest = manifest
        self.key = "plugin:" + manifest.id
        self.devices = []

    def probe(self, cancelled=lambda: False, timeout=10):
        from .plugin_process import PluginClient
        deadline = time.monotonic() + timeout
        with PluginClient(self.manifest, cancelled=cancelled, startup_timeout=min(5, timeout)) as client:
            data = client.request("discover", timeout=max(0.05, deadline - time.monotonic()))
        return [CameraDeviceInfo(self.key, d["id"], f'{d["name"]} — {self.manifest.name} (plugin)',
                                 d["serial"], d, d["vendor"]) for d in data]

    def discover(self):
        # The GUI updates this cache from a cancellable background search.
        return list(self.devices)

    def list_modes(self, device):
        return [CameraMode(**m) for m in device.native_info["modes"]] or [CameraMode(0, 0, "Default")]

    def create_thread(self, device, parent=None):
        from threads.plugin_camera_thread import PluginCameraThread
        return PluginCameraThread(self.manifest, device.id, parent)

    def close(self):
        pass  # Each probe/stream owns its helper and releases it independently.
