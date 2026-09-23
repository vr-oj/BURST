"""MMCore controls and declarative bindings to BURST's familiar controls."""
from dataclasses import replace
import math
from .controls import CameraControl

ALIASES = {
    "gain": ("Gain",), "fps": ("AcquisitionFrameRate", "Frame Rate", "FrameRate"),
    "auto_exposure": ("ExposureAuto", "Exposure Auto", "AutoExposure", "Auto Exposure"),
    "auto_gain": ("GainAuto", "Gain Auto", "AutoGain", "Auto Gain"),
    "pixel_format": ("PixelType", "Pixel Format", "PixelFormat"),
}
EXPOSURE_FACTORS = {"us": 1.0, "ms": 1000.0, "s": 1000000.0}


def validate_layout(core):
    components, depth = core.getNumberOfComponents(), core.getImageBitDepth()
    if not ((components == 1 and 1 <= depth <= 16) or (components == 4 and depth == 8)):
        raise ValueError("Select 8/16-bit monochrome or 32-bit RGB output supported by BURST.")
    byte_count = core.getBytesPerPixel()
    if isinstance(byte_count, int) and byte_count != (4 if components == 4 else 2 if depth > 8 else 1):
        raise ValueError("Packed pixel formats are not supported by this camera connection. Select unpacked Mono8/Mono16 or RGB output.")
    if core.getImageWidth() <= 0 or core.getImageHeight() <= 0:
        raise ValueError("The camera reports an empty image region.")


class MicroManagerControls:
    def __init__(self, session):
        self.session, self.core, self.camera = session, session.core, session.camera
        self.bindings = {}
        self.issues = {}
        self._idle_writable = set()
        self.fps_property = "Frame Rate" if session.trigger.library == "SpinnakerC" else "AcquisitionFrameRate"
        self.read_controls()  # Reject invalid saved mappings before starting acquisition.

    def native_controls(self):
        result = {}
        core, camera = self.core, self.camera
        for name in core.getDevicePropertyNames(camera):
            try:
                value = core.getProperty(camera, name)  # Refresh adapter's dynamic writability first.
                limited = bool(core.hasPropertyLimits(camera, name))
                try:
                    kind = {1: "str", 2: "float", 3: "int"}.get(core.getPropertyType(camera, name), "str")
                except Exception:
                    kind = "str"
                writable = not (core.isPropertyReadOnly(camera, name) or core.isPropertyPreInit(camera, name))
                if not self.session.acquiring:
                    if writable:
                        self._idle_writable.add(name)
                    else:
                        self._idle_writable.discard(name)
                requires_stop = self.session.acquiring and not writable and name in self._idle_writable
                result[name] = CameraControl(value,
                    core.getPropertyLowerLimit(camera, name) if limited else 0,
                    core.getPropertyUpperLimit(camera, name) if limited else 0,
                    choices=tuple(core.getAllowedPropertyValues(camera, name)),
                    writable=writable or requires_stop, requires_stop=requires_stop,
                    value_type=kind, limits_known=limited)
            except Exception:
                continue
        return result

    def read_controls(self):
        native = self.native_controls()
        result = {"mm:" + name: control for name, control in native.items()}
        saved = self.session.profile.get("bindings", {})
        self.bindings, self.issues = {}, {}
        for role, aliases in ALIASES.items():
            if role in saved:
                continue
            matches = [name for name in aliases if name in native]
            if len(matches) == 1:
                self.bindings[role] = {"property": matches[0]}
            elif len(matches) > 1:
                self.issues[role] = "Multiple matching properties; choose one in Advanced camera mapping."
        self.bindings.update(saved)
        for role, binding in self.bindings.items():
            name = binding["property"]
            if name not in native:
                raise ValueError(f"Saved {role} mapping refers to missing property '{name}'. Update Advanced camera mapping.")
            control = native[name]
            if role.startswith("auto_"):
                on, off = binding.get("on"), binding.get("off")
                if on is None:
                    if {"Continuous", "Off"} <= set(control.choices):
                        on, off = "Continuous", "Off"
                    elif {"On", "Off"} <= set(control.choices):
                        on, off = "On", "Off"
                    else:
                        self.issues[role] = "Map this adapter's automatic/manual values in Advanced camera mapping."
                        continue
                if on not in control.choices or off not in control.choices:
                    raise ValueError(f"Saved {role} enum values are no longer offered by the adapter.")
                binding.update(on=on, off=off)
                actual = str(control.value)
                result[role] = replace(control, value="Off" if actual == off else "Continuous" if actual == on else actual,
                                       choices=("Off", "Continuous"))
            elif role == "pixel_format":
                result[role] = control
            else:
                factor = EXPOSURE_FACTORS[binding["unit"]] if role == "exposure" else 1
                try:
                    value = float(control.value) * factor
                    numeric_choices = tuple(str(float(v) * factor) for v in control.choices)
                    if not math.isfinite(value):
                        raise ValueError("non-finite value")
                except (ValueError, TypeError):
                    if role in saved:
                        raise ValueError(f"Saved {role} mapping is not a finite numeric control.")
                    self.issues[role] = "This property is not a numeric control."
                    continue
                unit = binding.get("unit", "dB" if role == "gain" and self.session.trigger.library == "SpinnakerC"
                                   else "camera units" if role == "gain" else "fps")
                result[role] = replace(control, value=value, minimum=control.minimum * factor,
                    maximum=control.maximum * factor, increment=control.increment * factor,
                    unit="us" if role == "exposure" else unit,
                    choices=numeric_choices,
                    value_type="int" if control.value_type == "int" and factor == 1 else "float")
        if "exposure" not in saved:
            try:
                prop = native.get("Exposure")
                result["exposure"] = CameraControl(float(self.core.getExposure()) * 1000,
                    prop.minimum * 1000 if prop else 0, prop.maximum * 1000 if prop else 0,
                    writable=prop.writable if prop else True, unit="us",
                    requires_stop=bool(prop and prop.requires_stop),
                    limits_known=bool(prop and prop.limits_known))
            except Exception:
                self.issues["exposure"] = "Adapter does not provide MMCore exposure control."
        try:
            prop = native.get("Exposure")
            result["mmcore:Exposure (ms)"] = CameraControl(float(self.core.getExposure()),
                prop.minimum if prop else 0, prop.maximum if prop else 0,
                writable=prop.writable if prop else True, unit="ms",
                requires_stop=bool(prop and prop.requires_stop),
                limits_known=bool(prop and prop.limits_known))
        except Exception:
            pass
        try:
            result["mmcore:Sensor ROI (x,y,width,height)"] = CameraControl(
                ",".join(str(v) for v in self.core.getROI()), value_type="str", limits_known=False)
        except Exception:
            pass
        return result

    def set_value(self, name, value):
        control = self.read_controls().get(name)
        if control is None or not control.writable:
            raise RuntimeError("Property is read-only or requires configuration in Micro-Manager.")
        if control.choices:
            allowed = (float(value) in [float(v) for v in control.choices] if control.value_type in {"float", "int"}
                       else str(value) in control.choices)
            if not allowed:
                raise ValueError("Choose one of the adapter's allowed values.")
        if name in {"exposure", "gain", "fps", "mmcore:Exposure (ms)"} or control.value_type in {"float", "int"}:
            numeric = float(value)
            if not math.isfinite(numeric) or (control.value_type == "int" and not numeric.is_integer()):
                raise ValueError("Enter a finite number of the required type.")
            if control.limits_known and control.maximum > control.minimum and not control.minimum <= numeric <= control.maximum:
                raise ValueError(f"Value must be between {control.minimum:g} and {control.maximum:g}.")
            if name in {"exposure", "fps", "mmcore:Exposure (ms)"} and numeric <= 0:
                raise ValueError("Exposure and frame rate must be positive.")
        binding = self.bindings.get(name)
        roi_name = "mmcore:Sensor ROI (x,y,width,height)"
        previous = self.core.getROI() if name == roi_name else control.value
        running = self.session.acquiring
        if running:
            self.session.stop()

        def write(new_value):
            if name == roi_name:
                roi = tuple(int(p.strip()) for p in str(new_value).split(","))
                if len(roi) != 4 or any(v < 0 for v in roi) or ((roi[2] == 0 or roi[3] == 0) and roi != (0, 0, 0, 0)):
                    raise ValueError("Enter x,y,width,height; 0,0,0,0 restores the full sensor.")
                if roi == (0, 0, 0, 0):
                    self.core.clearROI()
                else:
                    self.core.setROI(*roi)
            elif name == "mmcore:Exposure (ms)" or (name == "exposure" and binding is None):
                self.core.setExposure(float(new_value) / (1000 if name == "exposure" else 1))
            else:
                prop_name = binding["property"] if binding else name.removeprefix("mm:")
                if name.startswith("auto_"):
                    new_value = binding["off" if new_value == "Off" else "on"]
                elif name == "exposure":
                    new_value = float(new_value) / EXPOSURE_FACTORS[binding["unit"]]
                native = self.native_controls()[prop_name]
                if native.value_type == "int":
                    if not float(new_value).is_integer():
                        raise ValueError("This camera control requires a whole number in its native units.")
                    new_value = int(float(new_value))
                unchanged = (float(native.value) == float(new_value) if native.value_type in {"float", "int"}
                             else str(native.value) == str(new_value))
                # MM float properties can round a maximum upward when read.
                # Do not write that rounded value back when already unchanged.
                if not unchanged:
                    self.core.setProperty(self.camera, prop_name, str(new_value))
            self.core.waitForDevice(self.camera)
        attempted = False
        try:
            current = self.read_controls().get(name)
            if current is None or not current.writable:
                raise RuntimeError("Property is unavailable with the current camera settings.")
            attempted = True
            write(value)
            validate_layout(self.core)
            self.read_controls()
            if running:
                self.session.start()
        except Exception:
            self.session.stop()
            try:
                if attempted:
                    write(",".join(str(v) for v in previous) if name == roi_name else previous)
                if running:
                    self.session.start()
            except Exception as restore_error:
                raise RuntimeError(f"Camera change failed and preview could not be restored: {restore_error}")
            raise

    def read_diagnostics(self):
        controls = self.read_controls()
        return {"backend": "Micro-Manager", "camera": self.camera, "device_adapter": self.session.trigger.library,
            "configuration": self.session.profile.get("config", "Discovered camera"),
            "core_version": self.core.getVersionInfo(), "adapter_api": self.core.getAPIVersionInfo(),
            "image_width": self.core.getImageWidth(), "image_height": self.core.getImageHeight(),
            "source_bit_depth": self.core.getImageBitDepth(), "control_issues": dict(self.issues),
            "timing": "Trigger setting readback does not certify physical timing",
            "properties": {key[3:]: c.value for key, c in controls.items() if key.startswith("mm:")}}
