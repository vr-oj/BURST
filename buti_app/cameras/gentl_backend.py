"""Optional Harvester bridge for installed SDKs that supply GenTL .cti producers."""
import importlib
import logging
import os
from pathlib import Path
from .controls import CameraControl, FLOAT_NODES, ENUM_NODES
from .models import CameraDeviceInfo, CameraMode, physical_identity

log = logging.getLogger(__name__)
SUPPORTED_FORMATS = ("Mono8", "Mono10", "Mono12", "Mono14", "Mono16", "RGB8", "BGR8",
                     "RGB8Packed", "BGR8Packed")


def producer_files():
    """Use advertised producer directories, never scan arbitrary SDK installations."""
    paths = []
    for variable in ("GENICAM_GENTL64_PATH", "BURST_GENTL_PATH"):
        for item in os.environ.get(variable, "").split(os.pathsep):
            if not item.strip():
                continue
            path = Path(os.path.expandvars(item.strip().strip('"'))).expanduser()
            if path.is_file() and path.suffix.lower() == ".cti":
                paths.append(str(path.resolve()))
            elif path.is_dir():
                paths.extend(str(p.resolve()) for p in sorted(path.glob("*.cti")))
    return list(dict.fromkeys(paths))


def identity(info):
    def read(name):
        try:
            return str(getattr(info, name) or "")
        except Exception:
            return ""
    return {name: read(name) for name in ("id_", "serial_number", "vendor", "model")}


class GenTLSession:
    def __init__(self, sdk, producer):
        self.sdk, self.producer = sdk, producer
        self.harvester = self.acquirer = None
        self.acquiring = False

    def __enter__(self):
        try:
            self.harvester = self.sdk.Harvester()
            self.harvester.add_file(self.producer, check_existence=True, check_validity=True)
            self.harvester.update()
            return self
        except Exception:
            self.close()
            raise

    def open(self, identifier):
        for index, info in enumerate(self.harvester.device_info_list):
            if identity(info)["id_"] == identifier:
                self.acquirer = self.harvester.create(index)
                return
        raise RuntimeError("GenTL camera unavailable. Refresh Devices and check the SDK connection.")

    def close(self):
        if self.acquirer is not None:
            if self.acquiring:
                try:
                    self.acquirer.stop()
                except Exception as exc:
                    log.warning("GenTL stop: %s", exc)
            try:
                self.acquirer.destroy()
            except Exception as exc:
                log.warning("GenTL device cleanup: %s", exc)
        self.acquiring = False
        self.acquirer = None
        if self.harvester is not None:
            try:
                self.harvester.reset()
            except Exception as exc:
                log.warning("GenTL producer cleanup: %s", exc)
        self.harvester = None

    def __exit__(self, *args):
        self.close()


class GenTLControls:
    def __init__(self, session, genapi):
        self.session, self.genapi = session, genapi

    def node(self, name):
        return getattr(self.session.acquirer.remote_device.node_map, name)

    def read_controls(self):
        result = {}
        for key, name in FLOAT_NODES.items():
            try:
                node = self.node(name)
                if not self.genapi.is_readable(node):
                    continue
                try:
                    step = node.inc
                except Exception:
                    step = 0
                result[key] = CameraControl(node.value, node.min, node.max, step,
                                            writable=self.genapi.is_writable(node))
            except Exception:
                pass
        for key, name in ENUM_NODES.items():
            try:
                node = self.node(name)
                if self.genapi.is_readable(node):
                    choices = tuple(node.symbolics)
                    if key == "pixel_format":
                        choices = tuple(p for p in choices if p in SUPPORTED_FORMATS)
                    result[key] = CameraControl(node.value, choices=choices,
                                                writable=self.genapi.is_writable(node))
            except Exception:
                pass
        return result

    def set_node(self, name, value):
        node = self.node(name)
        if not self.genapi.is_writable(node):
            if self.genapi.is_readable(node) and node.value == value:
                return
            raise RuntimeError(f"{name} is unavailable or locked")
        node.value = value

    def set_value(self, name, value):
        self.set_node((FLOAT_NODES | ENUM_NODES)[name], value)

    def list_modes(self):
        width, height, pixel_format = self.node("Width"), self.node("Height"), self.node("PixelFormat")
        formats = [p for p in pixel_format.symbolics if p in SUPPORTED_FORMATS]
        if pixel_format.value in formats:
            formats.remove(pixel_format.value)
            formats.insert(0, pixel_format.value)
        sizes = [(width.value, height.value), (width.max, height.max)]
        if self.genapi.is_writable(width) and self.genapi.is_writable(height):
            for divisor in (2, 4):
                sizes.append(tuple(node.min + ((max(node.min, node.max // divisor) - node.min)
                                              // max(1, node.inc)) * max(1, node.inc)
                                   for node in (width, height)))
        return list(dict.fromkeys(CameraMode(w, h, p) for w, h in sizes for p in formats))

    def configure(self, resolution, fps):
        for name, value in (("AcquisitionMode", "Continuous"), ("TriggerMode", "Off")):
            try:
                self.node(name)
            except AttributeError:
                continue
            self.set_node(name, value)
        if resolution:
            width, height, pixel_format = resolution
            if pixel_format not in SUPPORTED_FORMATS:
                raise RuntimeError(f"Unsupported GenTL format {pixel_format}; select Mono8 or RGB8.")
            self.set_node("PixelFormat", pixel_format)
            for name in ("OffsetX", "OffsetY"):
                try:
                    node = self.node(name)
                    if self.genapi.is_writable(node):
                        node.value = node.min
                except AttributeError:
                    pass
            for name, value in (("Width", width), ("Height", height)):
                node = self.node(name)
                if value:
                    inc = max(1, node.inc)
                    actual = node.min + ((min(value, node.max) - node.min) // inc) * inc
                    self.set_node(name, actual)
        for name, value in (("AcquisitionFrameRateEnable", True), ("AcquisitionFrameRate", fps)):
            try:
                self.set_node(name, value)
            except Exception:
                pass


class GenTLBackend:
    key = "gentl"
    module_name = "harvesters.core"

    def __init__(self, sdk):
        self.sdk = sdk
        self.genapi = importlib.import_module("genicam.genapi")

    def discover(self):
        devices = []
        producers = producer_files()
        if not producers:
            log.info("GenTL: no producer advertised in GENICAM_GENTL64_PATH or BURST_GENTL_PATH")
        for producer in producers:
            try:
                with GenTLSession(self.sdk, producer) as session:
                    for native in session.harvester.device_info_list:
                        info = identity(native)
                        if not info["id_"]:
                            continue
                        devices.append(CameraDeviceInfo(self.key, f"{producer}::{info['id_']}",
                            f"{info['model'] or info['id_']} (S/N: {info['serial_number'] or 'unknown'}) — {info['vendor']} / GenTL",
                            info["serial_number"] or None, {"producer": producer, "id": info["id_"]},
                            info["vendor"], physical_identity(info["vendor"], info["serial_number"])))
                    # DeviceInfo can reference native modules: release before Harvester.reset.
                    if session.harvester.device_info_list:
                        del native
            except Exception as exc:
                log.warning("GenTL producer %s unavailable: %s", producer, exc)
        return devices

    def list_modes(self, device):
        with GenTLSession(self.sdk, device.native_info["producer"]) as session:
            session.open(device.native_info["id"])
            return GenTLControls(session, self.genapi).list_modes()

    def create_thread(self, device, parent=None):
        from threads.gentl_camera_thread import GenTLCameraThread
        thread = GenTLCameraThread(parent, sdk=self.sdk, genapi=self.genapi)
        thread.set_device_info(device.native_info)
        return thread

    def close(self):
        pass
