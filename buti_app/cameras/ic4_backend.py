import logging
from .models import CameraDeviceInfo, CameraMode, physical_identity

log = logging.getLogger(__name__)


def reset_offsets(props):
    """Remove sensor cropping offsets before querying/applying full-frame sizes."""
    previous = {}
    for name in ("OffsetX", "OffsetY"):
        try:
            node = props.find_integer(name)
            previous[name] = node.value
            if node.value != node.minimum:
                node.value = node.minimum
        except Exception:
            # Not every IC4 device implements configurable offsets.
            pass
    return previous


def initialize(sdk):
    try:
        sdk.Library.init(api_log_level=sdk.LogLevel.INFO, log_targets=sdk.LogTarget.STDERR)
    except RuntimeError as exc:
        if "already called" not in str(exc):
            raise


class IC4Backend:
    key = "ic4"
    module_name = "imagingcontrol4"

    def __init__(self, sdk):
        self.sdk = sdk
        self._initialized = False

    def discover(self):
        if not self._initialized:
            initialize(self.sdk)
            self._initialized = True
        return [CameraDeviceInfo(
            self.key, str(getattr(dev, "unique_name", None) or dev.serial or dev.model_name),
            f"{dev.model_name} (S/N: {dev.serial}) — The Imaging Source / IC4",
            str(dev.serial) or None, dev, "The Imaging Source", physical_identity("The Imaging Source", dev.serial),
        ) for dev in self.sdk.DeviceEnum.devices()]

    def list_modes(self, device):
        grab = self.sdk.Grabber()
        modes = []
        try:
            grab.device_open(device.native_info)
            props = grab.device_property_map
            try:
                acq = props.find_enumeration("AcquisitionMode")
                names = [entry.name for entry in acq.entries]
                acq.value = "Continuous" if "Continuous" in names else names[0]
            except Exception:
                pass
            pf = props.find_enumeration("PixelFormat")
            original = pf.value
            geometry = {name: props.find_integer(name).value for name in ("Width", "Height")}
            offsets = reset_offsets(props)
            try:
                for entry in pf.entries:
                    try:
                        pf.value = entry.name
                        reset_offsets(props)
                        width = props.find_integer("Width")
                        height = props.find_integer("Height")
                        modes.append(CameraMode(width.value, height.value, entry.name))
                        # Current dimensions can be a saved crop or a UVC default.
                        # They are not the full set of camera-supported dimensions.
                        try:
                            modes.append(CameraMode(width.maximum, height.maximum, entry.name))
                        except Exception as exc:
                            log.debug("IC4 maximum size unavailable for %s: %s", entry.name, exc)
                    except Exception as exc:
                        log.debug("IC4 format %s unavailable: %s", entry.name, exc)
            finally:
                try:
                    pf.value = original
                finally:
                    reset_offsets(props)
                    for name, value in (geometry | offsets).items():
                        try:
                            node = props.find_integer(name)
                            if node.value != value:
                                node.value = value
                        except Exception as exc:
                            log.warning("Could not restore IC4 %s after mode discovery: %s", name, exc)
            modes = sorted(set(modes), key=lambda mode: (
                -mode.width * mode.height, mode.pixel_format != "Mono8", mode.pixel_format))
            log.info("IC4 acquisition modes: %s", ", ".join(mode.display_name for mode in modes))
            return modes
        finally:
            try:
                grab.device_close()
            except Exception:
                pass

    def create_thread(self, device, parent=None):
        from threads.sdk_camera_thread import SDKCameraThread
        thread = SDKCameraThread(parent)
        thread.set_device_info(device.native_info)
        return thread

    def close(self):
        if self._initialized:
            self.sdk.Library.shutdown()
            self._initialized = False
