"""Translate MM device-adapter controls without assuming SDK property names."""
from .trigger import AUTO_TRIGGER, configure_external_trigger, verify_external_trigger


# SpinnakerC exposes spaced names; other GenICam adapters use the node names.
# https://github.com/micro-manager/mmCoreAndDevices/blob/main/DeviceAdapters/SpinnakerC/SpinnakerCCamera.cpp
TRIGGER_PROPERTIES = {
    "TriggerMode": ("TriggerMode", "Trigger Mode"),
    "TriggerSelector": ("TriggerSelector", "Trigger Selector"),
    "TriggerSource": ("TriggerSource", "Trigger Source"),
    "TriggerActivation": ("TriggerActivation", "Trigger Activation"),
}


class MicroManagerTrigger:
    def __init__(self, core, camera):
        self.core, self.camera = core, camera
        self.library = str(core.getDeviceLibrary(camera))
        names = set(core.getDevicePropertyNames(camera))
        self.properties = {key: next((name for name in aliases if name in names), None)
                           for key, aliases in TRIGGER_PROPERTIES.items()}
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
        if not self.properties["TriggerMode"]:
            return
        current, choices = self.read("TriggerMode"), self.choices("TriggerMode")
        if "Off" in choices or current in {"Off", "On"}:
            value = "Off"
        elif "Internal" in choices:
            value = "Internal"
        else:
            raise RuntimeError(
                f"{self.library}: configure free-running preview in Micro-Manager first.")
        if current != value:
            self.write("TriggerMode", value)
        verify_external_trigger(
            lambda name: self.core.getProperty(self.camera, name),
            {self.properties["TriggerMode"]: value})

    def arm(self, source):
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
                "This does not mean the camera lacks triggering. Use a supported camera connection "
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
