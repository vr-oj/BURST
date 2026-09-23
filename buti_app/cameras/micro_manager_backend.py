"""Optional MMCore integration. Configurations and vendor adapters stay external."""
import logging
import os
from pathlib import Path

from .controls import CameraControl
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
    installation = Path(profile.get("installation", ""))
    config = Path(profile.get("config", ""))
    if not str(profile.get("installation", "")).strip() or not installation.is_dir():
        raise ValueError("Select the Micro-Manager installation folder containing its device adapters.")
    if not config.is_file() or config.suffix.lower() != ".cfg":
        raise ValueError("Select an existing Micro-Manager hardware configuration (.cfg).")
    return {"installation": str(installation.resolve()), "config": str(config.resolve()),
            "camera": str(profile.get("camera", ""))}


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
            self.trigger = MicroManagerTrigger(self.core, camera)
            return self
        except Exception:
            self.close()
            raise

    def start(self):
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


class MicroManagerControls:
    def __init__(self, session):
        self.session = session
        self.core, self.camera = session.core, session.camera
        self.fps_property = "AcquisitionFrameRate"
        if session.trigger.library == "SpinnakerC":
            self.fps_property = "Frame Rate"

    def read_controls(self):
        core, camera = self.core, self.camera
        result = {}
        for name in core.getDevicePropertyNames(camera):
            try:
                limited = core.hasPropertyLimits(camera, name)
                result["mm:" + name] = CameraControl(
                    core.getProperty(camera, name),
                    core.getPropertyLowerLimit(camera, name) if limited else 0,
                    core.getPropertyUpperLimit(camera, name) if limited else 0,
                    choices=tuple(core.getAllowedPropertyValues(camera, name)),
                    writable=not (core.isPropertyReadOnly(camera, name) or core.isPropertyPreInit(camera, name)))
            except Exception as exc:
                log.debug("Micro-Manager property %s unavailable: %s", name, exc)
        # MMCore defines exposure in ms. Gain units and auto enums are adapter
        # specific: expose their native properties instead of mislabelling dB.
        exposure = result.get("mm:Exposure")
        if exposure and exposure.maximum > exposure.minimum:
            result["exposure"] = CameraControl(core.getExposure() * 1000,
                exposure.minimum * 1000, exposure.maximum * 1000, writable=exposure.writable)
        fps = result.get("mm:" + self.fps_property)
        if fps and fps.maximum > fps.minimum:
            try:
                result["fps"] = CameraControl(float(fps.value), fps.minimum, fps.maximum, writable=fps.writable)
            except ValueError:
                pass
        result["mmcore:Exposure (ms)"] = CameraControl(str(core.getExposure()))
        try:
            result["mmcore:Sensor ROI (x,y,width,height)"] = CameraControl(
                ",".join(str(v) for v in core.getROI()))
        except Exception:
            pass
        pixel = result.get("mm:PixelType")
        if pixel:
            result["pixel_format"] = CameraControl(pixel.value, choices=(str(pixel.value),), writable=False)
        return result

    def set_value(self, name, value):
        control = self.read_controls().get(name)
        if control is None or not control.writable:
            raise RuntimeError("Property is read-only or requires configuration in Micro-Manager.")
        if control.choices and str(value) not in control.choices:
            raise ValueError("Choose one of the adapter's allowed values.")
        if control.maximum > control.minimum and not control.minimum <= float(value) <= control.maximum:
            raise ValueError(f"Value must be between {control.minimum:g} and {control.maximum:g}.")
        running = self.session.acquiring
        if running:
            self.session.stop()
        try:
            if name == "exposure" or name == "mmcore:Exposure (ms)":
                exposure = float(value) / 1000 if name == "exposure" else float(value)
                if not 0 < exposure < float("inf"):
                    raise ValueError("Exposure must be a finite positive number in milliseconds.")
                self.core.setExposure(exposure)
            elif name == "mmcore:Sensor ROI (x,y,width,height)":
                roi = tuple(int(part.strip()) for part in str(value).split(","))
                if len(roi) != 4 or any(v < 0 for v in roi):
                    raise ValueError("Enter x,y,width,height; use 0,0,0,0 to restore the full sensor.")
                if roi == (0, 0, 0, 0):
                    self.core.clearROI()
                elif roi[2] and roi[3]:
                    self.core.setROI(*roi)
                else:
                    raise ValueError("Width and height must be positive.")
            elif name == "fps":
                self.core.setProperty(self.camera, self.fps_property, str(value))
            else:
                self.core.setProperty(self.camera, name.removeprefix("mm:"), str(value))
            self.core.waitForDevice(self.camera)
        finally:
            if running:
                self.session.start()

    def read_diagnostics(self):
        return {"backend": "Micro-Manager", "camera": self.camera,
                "device_adapter": self.session.trigger.library,
                "configuration": self.session.profile["config"],
                "core_version": self.core.getVersionInfo(),
                "adapter_api": self.core.getAPIVersionInfo(),
                "image_width": self.core.getImageWidth(), "image_height": self.core.getImageHeight(),
                "source_bit_depth": self.core.getImageBitDepth(),
                "output": "8-bit mono or RGB; high-bit-depth mono uses fixed scaling",
                "timing": "Configuration controls triggering; synchronization is not verified",
                "properties": {key[3:]: value.value for key, value in self.read_controls().items()
                               if key.startswith("mm:")}}


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
            if not isinstance(profile, dict) or not all(profile.get(k) for k in ("installation", "config", "camera")):
                continue
            key = f"{profile['installation']}::{profile['config']}::{profile['camera']}"
            devices.append(CameraDeviceInfo(self.key, key,
                f"{profile['camera']} — Micro-Manager ({Path(profile['config']).stem})",
                native_info=dict(profile)))
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
