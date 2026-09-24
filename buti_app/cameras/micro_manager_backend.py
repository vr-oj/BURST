"""Optional MMCore integration. Configurations and vendor adapters stay external."""
import logging
import os
from pathlib import Path

from .micro_manager_controls import MicroManagerControls
from .micro_manager_profiles import normalize_profile, profile_key
from .models import CameraDeviceInfo, CameraMode
from .micro_manager_trigger import MicroManagerTrigger

log = logging.getLogger(__name__)
PROFILE_SETTING = "micro_manager_profiles"


def installation_candidates():
    roots = [Path(os.environ.get("ProgramFiles", "C:/Program Files")),
             Path("/Applications"), Path("/usr/local/lib")]
    return [str(p) for root in roots if root.is_dir()
            for p in sorted(root.glob("*Micro-Manager*")) if p.is_dir()]


def validate_profile(profile):
    return normalize_profile(profile)


class MicroManagerSession:
    def __init__(self, sdk, profile):
        self.sdk, self.profile = sdk, profile
        self.core = None
        self.dll_handle = None
        self.acquiring = False

    def __enter__(self):
        try:
            self.profile = validate_profile(self.profile)
            if os.name == "nt":
                self.dll_handle = os.add_dll_directory(self.profile["installation"])
            self.core = self.sdk.CMMCore()
            self.core.setTimeoutMs(5000)
            self.core.setDeviceAdapterSearchPaths([self.profile["installation"]])
            try:
                connection = self.profile.get("connection")
                if connection:
                    camera = self.profile["camera"]
                    self.core.loadDevice(camera, connection["library"], connection["device"])
                    for name, value in connection.get("pre_init", {}).items():
                        if not self.core.isPropertyPreInit(camera, name):
                            raise ValueError(f"'{name}' is no longer an initialization setting.")
                        self.core.setProperty(camera, name, value)
                    self.core.initializeDevice(camera)
                else:
                    self.core.loadSystemConfiguration(self.profile["config"])
            except Exception as exc:
                raise RuntimeError(f"Could not load configuration. BURST uses {self.core.getAPIVersionInfo()}. "
                                   f"Check matching adapters and vendor dependencies. Driver message: {exc}") from exc
            # BURST owns only camera acquisition, not microscope shutter sequencing.
            self.core.setAutoShutter(False)
            cameras = list(self.core.getLoadedDevicesOfType(self.sdk.CameraDevice))
            camera = self.profile["camera"] or self.core.getCameraDevice() or (cameras[0] if cameras else "")
            if camera not in cameras:
                raise RuntimeError("The configuration has no selected camera. Configure a camera in Micro-Manager first.")
            self.core.setCameraDevice(camera)
            self.camera = camera
            self.trigger = MicroManagerTrigger(self.core, camera, self.profile.get("timing"),
                                               self.profile.get("bindings"))
            return self
        except Exception:
            self.close()
            raise

    def start(self):
        from .micro_manager_controls import validate_layout
        validate_layout(self.core)
        if self.core.getNumberOfCameraChannels() != 1:
            raise RuntimeError("Multi-channel camera configurations are not supported. Select a single camera channel.")
        self.core.clearCircularBuffer()
        # MMCore's interval argument is unused by many adapters. Never call it a
        # guaranteed frame-rate setting; delivery is checked by BURST preflight.
        self.acquiring = True
        # A large finite sequence is not equivalent to continuous acquisition:
        # adapters such as SpinnakerC select hardware MultiFrame and its limited
        # frame counter. Use the dedicated indefinite preview API.
        self.core.startContinuousSequenceAcquisition(100.0)

    def stop(self):
        if self.core is not None and self.acquiring:
            self.trigger.prepare_stop()
            self.core.stopSequenceAcquisition()
            self.acquiring = False

    def close(self):
        if self.core is not None:
            try:
                self.stop()
            except Exception:
                log.exception("Micro-Manager could not stop acquisition")
            try:
                self.core.unloadAllDevices()
            except Exception:
                log.exception("Micro-Manager could not unload devices")
            self.core = None
        if self.dll_handle is not None:
            self.dll_handle.close()
            self.dll_handle = None

    def __exit__(self, *args):
        self.close()


class MicroManagerBackend:
    key = "micromanager"
    module_name = "pymmcore"

    def __init__(self, sdk):
        self.sdk = sdk
        self.profiles = []

    def discover(self):
        # A saved profile is a candidate, not proof the camera is connected. Do
        # not initialize a complete microscope during automatic device refresh.
        devices = []
        for profile in self.profiles:
            if not isinstance(profile, dict) or not profile.get("installation") or not profile.get("camera") or not (profile.get("config") or profile.get("connection")):
                continue
            key = profile_key(profile)
            connection = profile.get("connection", {})
            label = profile.get("display_name", profile["camera"])
            devices.append(CameraDeviceInfo(self.key, key,
                f"{label} — Micro-Manager ({connection.get('library') or Path(profile.get('config', '')).stem})",
                serial=profile.get("serial"), native_info=dict(profile),
                vendor=profile.get("vendor", ""), physical_id=profile.get("physical_id")))
        return devices

    def list_modes(self, device):
        mode = device.native_info.get("configured_mode", {})
        if (isinstance(mode, dict) and isinstance(mode.get("width"), int)
                and isinstance(mode.get("height"), int) and mode["width"] > 0 and mode["height"] > 0):
            return [CameraMode(mode["width"], mode["height"], "Configuration")]
        return [CameraMode(0, 0, "Configuration")]

    def create_thread(self, device, parent=None):
        from threads.mmcore_camera_thread import MMCoreCameraThread
        return MMCoreCameraThread(parent, sdk=self.sdk, profile=device.native_info)

    def close(self):
        pass
