"""Spinnaker handles live only inside a discovery/mode/acquisition session."""
import logging
from .models import CameraDeviceInfo, CameraMode, physical_identity
from .controls import CameraControl, FLOAT_NODES, ENUM_NODES

log = logging.getLogger(__name__)


def device_identity(sdk, camera):
    nodemap = camera.GetTLDeviceNodeMap()

    def read(name):
        try:
            node = sdk.CStringPtr(nodemap.GetNode(name))
            return str(node.GetValue()) if sdk.IsReadable(node) else ""
        except Exception:
            return ""

    return {key: read(node) for key, node in (
        ("model", "DeviceModelName"), ("serial", "DeviceSerialNumber"),
        ("vendor", "DeviceVendorName"), ("id", "DeviceID"))}


class SpinnakerSession:
    def __init__(self, sdk):
        self.sdk = sdk
        self.system = self.cameras = self.camera = None
        self.initialized = self.acquiring = False

    def __enter__(self):
        try:
            self.system = self.sdk.System.GetInstance()
            self.cameras = self.system.GetCameras()
            return self
        except Exception:
            self.close()
            raise

    def open(self, identifier):
        for index in range(self.cameras.GetSize()):
            camera = self.cameras.GetByIndex(index)
            try:
                info = device_identity(self.sdk, camera)
                if (info["id"] or info["serial"]) == identifier:
                    self.camera = camera
                    break
            finally:
                del camera
        if self.camera is None:
            raise RuntimeError("FLIR camera is unavailable or disconnected. Refresh Devices and try again.")
        self.camera.Init()
        self.initialized = True

    def close(self):
        # Attempt each cleanup even when a disconnected device rejects earlier calls.
        if self.camera is not None:
            if self.acquiring:
                try:
                    self.camera.EndAcquisition()
                except Exception as exc:
                    log.warning("Spinnaker EndAcquisition: %s", exc)
            if self.initialized:
                try:
                    self.camera.DeInit()
                except Exception as exc:
                    log.warning("Spinnaker DeInit: %s", exc)
        self.acquiring = self.initialized = False
        self.camera = None
        if self.cameras is not None:
            try:
                self.cameras.Clear()
            except Exception as exc:
                log.warning("Spinnaker camera list cleanup: %s", exc)
        self.cameras = None
        if self.system is not None:
            try:
                self.system.ReleaseInstance()
            except Exception as exc:
                log.warning("Spinnaker system cleanup: %s", exc)
        self.system = None

    def __exit__(self, *args):
        self.close()


class SpinnakerControls:
    def __init__(self, session):
        self.session = session
        self.sdk = session.sdk

    def node(self, name, kind):
        return getattr(self.sdk, f"C{kind}Ptr")(self.session.camera.GetNodeMap().GetNode(name))

    def choices(self, node):
        return tuple(self.sdk.CEnumEntryPtr(entry).GetSymbolic() for entry in node.GetEntries()
                     if self.sdk.IsReadable(entry))

    def read_controls(self):
        result = {}
        for key, name in FLOAT_NODES.items():
            try:
                node = self.node(name, "Float")
                if self.sdk.IsReadable(node):
                    result[key] = CameraControl(node.GetValue(), node.GetMin(), node.GetMax(),
                                                writable=self.sdk.IsWritable(node))
            except Exception:
                pass
        for key, name in ENUM_NODES.items():
            try:
                node = self.node(name, "Enumeration")
                if self.sdk.IsReadable(node):
                    result[key] = CameraControl(node.GetCurrentEntry().GetSymbolic(),
                                                choices=self.choices(node), writable=self.sdk.IsWritable(node))
            except Exception:
                pass
        return result

    def set_enum(self, name, value):
        node = self.node(name, "Enumeration")
        if not self.sdk.IsWritable(node):
            raise RuntimeError(f"{name} is unavailable or locked")
        entry = node.GetEntryByName(value)
        if not self.sdk.IsReadable(entry):
            raise RuntimeError(f"{name} does not support {value}")
        node.SetIntValue(entry.GetValue())

    def set_value(self, name, value):
        if name in FLOAT_NODES:
            node = self.node(FLOAT_NODES[name], "Float")
            if not self.sdk.IsWritable(node):
                raise RuntimeError(f"{name} is unavailable or locked")
            requested = float(value)
            applied = max(node.GetMin(), min(requested, node.GetMax()))
            node.SetValue(applied)
            if name == "fps" and abs(node.GetValue() - requested) > 0.01:
                raise RuntimeError(f"Requested {requested:g} FPS; camera allows/applied {node.GetValue():.2f} FPS. "
                                   "Check resolution, exposure, USB connection, and bandwidth limits.")
        else:
            self.set_enum(ENUM_NODES[name], value)

    def read_diagnostics(self):
        result = {}
        for name in ("TriggerMode", "TriggerSource", "AcquisitionFrameRate", "AcquisitionResultingFrameRate", "ExposureTime",
                     "DeviceLinkThroughputLimit", "DeviceLinkCurrentThroughput", "DeviceMaxThroughput"):
            try:
                node = self.sdk.CValuePtr(self.session.camera.GetNodeMap().GetNode(name))
                if self.sdk.IsReadable(node):
                    result[name] = node.ToString()
            except Exception:
                pass
        return result

    def configure(self, resolution, fps):
        for name, value in (("AcquisitionMode", "Continuous"), ("TriggerMode", "Off")):
            node = self.node(name, "Enumeration")
            if self.sdk.IsReadable(node):
                if node.GetCurrentEntry().GetSymbolic() != value:
                    self.set_enum(name, value)
        if resolution:
            width, height, pixel_format = resolution
            self.set_enum("PixelFormat", pixel_format)
            for name in ("OffsetX", "OffsetY"):
                node = self.node(name, "Integer")
                if self.sdk.IsWritable(node):
                    node.SetValue(node.GetMin())
            for name, value in (("Width", width), ("Height", height)):
                node = self.node(name, "Integer")
                if value and self.sdk.IsWritable(node):
                    inc = max(1, node.GetInc())
                    actual = node.GetMin() + ((min(value, node.GetMax()) - node.GetMin()) // inc) * inc
                    node.SetValue(actual)
        try:
            enable = self.node("AcquisitionFrameRateEnable", "Boolean")
            if self.sdk.IsWritable(enable):
                enable.SetValue(True)
        except Exception:
            pass
        for name, value in (("auto_exposure", "Off"), ("auto_gain", "Off"),
                            ("exposure", 10000), ("gain", 5), ("fps", fps)):
            try:
                self.set_value(name, value)
            except Exception as exc:
                log.warning("Spinnaker default %s could not be fully applied: %s", name, exc)
        log.info("Spinnaker acquisition configuration: %s", self.read_diagnostics())

    def list_modes(self):
        width, height = self.node("Width", "Integer"), self.node("Height", "Integer")
        pf = self.node("PixelFormat", "Enumeration")
        current = pf.GetCurrentEntry().GetSymbolic()
        # Current format plus common convertible formats; no integer-range Cartesian product.
        formats = [current] + [p for p in self.choices(pf)
                               if p in {"Mono8", "Mono16", "RGB8", "BGR8"} and p != current]
        sizes = [(width.GetValue(), height.GetValue()), (width.GetMax(), height.GetMax())]
        if self.sdk.IsWritable(width) and self.sdk.IsWritable(height):
            for divisor in (2, 4):
                dimensions = []
                for node in (width, height):
                    minimum, step = node.GetMin(), max(1, node.GetInc())
                    requested = max(minimum, node.GetMax() // divisor)
                    dimensions.append(minimum + ((requested - minimum) // step) * step)
                sizes.append(tuple(dimensions))
        return list(dict.fromkeys(CameraMode(w, h, p) for w, h in sizes for p in formats))


class SpinnakerBackend:
    key = "spinnaker"
    module_name = "PySpin"

    def __init__(self, sdk):
        if not hasattr(sdk, "System"):
            raise RuntimeError("PySpin is not the Teledyne Spinnaker binding. Install the matching SDK wheel.")
        self.sdk = sdk

    def discover(self):
        devices = []
        with SpinnakerSession(self.sdk) as session:
            for index in range(session.cameras.GetSize()):
                camera = session.cameras.GetByIndex(index)
                try:
                    info = device_identity(self.sdk, camera)
                finally:
                    del camera
                identifier = info["id"] or info["serial"]
                if not identifier:
                    log.warning("Skipping Spinnaker camera without a stable identifier")
                    continue
                devices.append(CameraDeviceInfo(self.key, identifier,
                    f"{info['model'] or 'FLIR Camera'} (S/N: {info['serial'] or 'unknown'}) — FLIR / Spinnaker",
                    info["serial"] or None, identifier, info["vendor"], physical_identity(info["vendor"], info["serial"])))
        return devices

    def list_modes(self, device):
        with SpinnakerSession(self.sdk) as session:
            session.open(device.id)
            return SpinnakerControls(session).list_modes()

    def create_thread(self, device, parent=None):
        from threads.spinnaker_camera_thread import SpinnakerCameraThread
        thread = SpinnakerCameraThread(parent, sdk=self.sdk)
        thread.set_device_info(device.id)
        return thread

    def close(self):
        pass  # Sessions own and release every native reference.
