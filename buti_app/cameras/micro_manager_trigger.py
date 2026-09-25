"""Translate MM device-adapter controls without assuming SDK property names."""
import logging

from .trigger import AUTO_TRIGGER, configure_external_trigger, verify_external_trigger

log = logging.getLogger(__name__)

# SpinnakerC exposes spaced names; other GenICam adapters use the node names.
# https://github.com/micro-manager/mmCoreAndDevices/blob/main/DeviceAdapters/SpinnakerC/SpinnakerCCamera.cpp
TRIGGER_PROPERTIES = {
    "TriggerMode": ("TriggerMode", "Trigger Mode"),
    "TriggerSelector": ("TriggerSelector", "Trigger Selector"),
    "TriggerSource": ("TriggerSource", "Trigger Source"),
    "TriggerActivation": ("TriggerActivation", "Trigger Activation"),
}


class MicroManagerTrigger:
    def __init__(self, core, camera, timing=None, bindings=None):
        self.core, self.camera = core, camera
        self.timing = timing or {}
        if self.timing:
            names = set(core.getDevicePropertyNames(camera))
            protected = {"Exposure", "ExposureTime", "Exposure Time", "Gain", "PixelType", "Pixel Format", "PixelFormat", "Binning",
                         "Width", "Height", "OffsetX", "OffsetY", "ExposureAuto", "Exposure Auto", "Auto Exposure",
                         "AutoExposure", "GainAuto", "Gain Auto", "Auto Gain", "AutoGain"}
            protected.update(b["property"] for role, b in (bindings or {}).items()
                             if role in {"exposure", "gain", "pixel_format", "auto_exposure", "auto_gain"})
            for assignments in self.timing.values():
                for item in assignments:
                    name = item["property"]
                    if name not in names or core.isPropertyPreInit(camera, name) or name in protected:
                        raise ValueError(f"Timing mapping '{name}' is unavailable, setup-only, or changes image settings.")
                    choices = tuple(core.getAllowedPropertyValues(camera, name))
                    if choices and item["value"] not in choices:
                        raise ValueError(f"Timing value '{item['value']}' is not offered for '{name}'.")
        self.library = str(core.getDeviceLibrary(camera))
        names = set(core.getDevicePropertyNames(camera))
        matches = {key: [name for name in aliases if name in names] for key, aliases in TRIGGER_PROPERTIES.items()}
        self.ambiguous = [key for key, values in matches.items() if len(values) > 1]
        self.properties = {key: values[0] if len(values) == 1 else None for key, values in matches.items()}
        # TIScam implements get/setExternalTrigger through Internal/External.
        # Do not infer the same semantics for an unrelated adapter's enum.
        # https://github.com/micro-manager/mmCoreAndDevices/blob/main/DeviceAdapters/TISCam/TIScamera.cpp
        self.tis_external = (self.library.casefold() == "tiscam"
                             and self.properties["TriggerMode"] == "TriggerMode"
                             and {"Internal", "External"} <= set(self.choices("TriggerMode")))

    def choices(self, key):
        return tuple(self.core.getAllowedPropertyValues(self.camera, self.properties[key]))

    def read(self, key):
        return str(self.core.getProperty(self.camera, self.properties[key]))

    def write(self, key, value):
        self.core.setProperty(self.camera, self.properties[key], value)

    def preview(self):
        if self.timing.get("preview"):
            self._apply_mapping("preview")
            return
        if "TriggerMode" in self.ambiguous:
            log.info("%s preview: keeping configured trigger properties (multiple mode controls).", self.library)
            return
        if not self.properties["TriggerMode"]:
            return
        current, choices = self.read("TriggerMode"), self.choices("TriggerMode")
        if "Off" in choices or current in {"Off", "On"}:
            value = "Off"
        elif "Internal" in choices:
            value = "Internal"
        else:
            # MMCore has a common sequence-acquisition API, but no universal
            # trigger-mode enum. A usable camera configuration must not be
            # rejected just because its adapter uses unfamiliar property values.
            # Try that configuration; actual frame delivery is checked by the
            # acquisition thread. This does not authorize external recording.
            log.info("%s preview: using configured %s=%r (available: %s).",
                     self.library, self.properties["TriggerMode"], current, choices)
            return
        if current != value:
            self.write("TriggerMode", value)
        verify_external_trigger(
            lambda name: self.core.getProperty(self.camera, name),
            {self.properties["TriggerMode"]: value})

    def arm(self, source):
        if self.timing.get("external"):
            try:
                configured = self._apply_mapping("external")
                return configured, {"name": "User-configured external input", "selection": "saved_mapping",
                                    "adapter": self.library, "physical_timing": "not_verified"}
            except Exception:
                self._apply_mapping("preview")
                raise
        if self.tis_external:
            if source != AUTO_TRIGGER:
                raise RuntimeError("TIScam uses the camera's configured external input; "
                                   "it cannot select a named Line input through Micro-Manager.")
            self.write("TriggerMode", "External")
            configured = {"TriggerMode": "External"}
            verify_external_trigger(lambda name: self.core.getProperty(self.camera, name), configured)
            return configured, {
                "name": "Camera-configured external input", "selection": "adapter_configuration",
                "adapter": self.library,
                "not_exposed": ["TriggerSource", "TriggerSelector", "TriggerActivation"],
            }
        missing = [key for key, name in self.properties.items() if name is None]
        if missing:
            raise RuntimeError(
                f"{self.library}: BURST cannot yet configure external triggering through this "
                f"Micro-Manager adapter (controls not exposed: {', '.join(missing)}). "
                "This does not mean the camera lacks triggering. Configure Advanced camera mapping or use a supported camera connection "
                "or explicitly choose approximate software pairing under Acquisition > Advanced. "
                "BURST has not started the Arduino.")
        configured = configure_external_trigger(
            self.read, self.write, source, choices=lambda: self.choices("TriggerSource"))
        return ({self.properties[key]: value for key, value in configured.items()},
                {"name": configured["TriggerSource"], "selection": "camera_property",
                 "adapter": self.library})

    def prepare_stop(self):
        # TIScam waits indefinitely in snapImages during an external sequence.
        # Release that wait before stopSequenceAcquisition joins its thread. This
        # is used only after recording has detached/drained, or during cleanup;
        # any resulting preview images are discarded when the buffer is cleared.
        if self.tis_external and self.read("TriggerMode") == "External":
            self.preview()

    def _apply_mapping(self, mode):
        expected = {}
        for item in self.timing[mode]:
            name, value = item["property"], item["value"]
            if str(self.core.getProperty(self.camera, name)) != value:
                self.core.setProperty(self.camera, name, value)
            expected[name] = value
        verify_external_trigger(lambda name: self.core.getProperty(self.camera, name), expected)
        return expected
