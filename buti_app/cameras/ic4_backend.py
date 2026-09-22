import logging
from .models import CameraDeviceInfo, CameraMode, physical_identity

log = logging.getLogger(__name__)


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
            try:
                for entry in pf.entries:
                    try:
                        pf.value = entry.name
                        modes.append(CameraMode(props.find_integer("Width").value,
                                                props.find_integer("Height").value, entry.name))
                    except Exception:
                        pass
            finally:
                pf.value = original
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
