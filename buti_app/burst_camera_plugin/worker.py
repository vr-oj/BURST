"""Standalone bridge shipped as source data for external plugin environments."""
import ctypes
import importlib
import json
import logging
import math
import os
from pathlib import Path
import sys
from dataclasses import asdict

# -I excludes the script directory. Import our API before the plugin can import
# its own dependencies. Never import the BURST GUI in this process.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from burst_camera_plugin import API_VERSION, CameraPlugin, Control, Device, Frame, Mode, TriggerState

log = logging.getLogger(__name__)
STANDARD = {"exposure", "gain", "fps", "auto_exposure", "auto_gain", "pixel_format"}


class ControlRejected(ValueError):
    """A request rejected before any SDK setting was changed."""


def json_data(value):
    return json.loads(json.dumps(value, allow_nan=False))


def controls_data(controls):
    result = {}
    if not isinstance(controls, dict):
        raise ValueError("controls() must return a dictionary")
    for name, c in controls.items():
        if not isinstance(name, str) or (name not in STANDARD and not name.startswith("vendor:")):
            raise ValueError(f"Use a standard control name or vendor: prefix: {name}")
        if not isinstance(c, Control):
            raise ValueError(f"Control {name} must use the BURST Control type")
        if c.value_type not in {"float", "int", "enum", "str"}:
            raise ValueError(f"Invalid control value type: {name}")
        if any(not isinstance(v, str) for v in c.choices):
            raise ValueError(f"Control choices must be strings: {name}")
        if name in {"exposure", "gain", "fps"}:
            if c.value_type not in {"float", "int"} or not math.isfinite(float(c.value)):
                raise ValueError(f"{name} must be numeric; expose named modes under vendor:")
            if c.increment < 0 or (c.limits_known and c.maximum < c.minimum):
                raise ValueError(f"Invalid control limits: {name}")
        if name in {"auto_exposure", "auto_gain"}:
            if c.value not in {"Off", "Continuous"} or not set(c.choices).issubset({"Off", "Continuous"}):
                raise ValueError(f"{name} must normalize native values to Off/Continuous")
        unit = {"exposure": "us", "fps": "Hz"}.get(name)
        if unit and c.unit not in {"", unit}:
            raise ValueError(f"{name} must be expressed in {unit}")
        result[name] = asdict(c)
        result[name]["unit"] = unit or c.unit or ("camera units" if name == "gain" else "")
    return json_data(result)


def trigger_data(state, source):
    if (not isinstance(state, TriggerState) or type(state.external) is not bool
            or state.external != bool(source) or not isinstance(state.settings, dict)
            or any(not isinstance(name, str) for name in state.settings)
            or (state.input is not None and not isinstance(state.input, str))):
        raise RuntimeError("Camera did not confirm the requested acquisition timing")
    if source and (not state.settings or not state.input or state.input.lower() in {"auto", "software", "internal"}):
        raise RuntimeError("External triggering needs verified settings and a physical input")
    if source and source != "auto" and state.input != source:
        raise RuntimeError("Trigger readback uses a different input")
    return json_data(asdict(state))


def frame_data(frame):
    import numpy as np
    if not isinstance(frame, Frame):
        raise ValueError("next_frame() must return Frame or None")
    pixels = np.asarray(frame.pixels)
    mono = pixels.ndim == 2 and pixels.dtype in (np.dtype("uint8"), np.dtype("uint16"))
    rgb = pixels.ndim == 3 and pixels.shape[2] == 3 and pixels.dtype == np.dtype("uint8")
    if not (mono or rgb) or min(pixels.shape) <= 0:
        raise ValueError(f"Unsupported plugin image layout: {pixels.shape}, {pixels.dtype}")
    if type(frame.bit_depth) is not int or not 1 <= frame.bit_depth <= pixels.dtype.itemsize * 8 or (rgb and frame.bit_depth != 8):
        raise ValueError("Invalid plugin image bit depth")
    if frame.camera_frame_id is not None and (type(frame.camera_frame_id) is not int or frame.camera_frame_id < 0):
        raise ValueError("camera_frame_id must be a genuine nonnegative camera counter, or None")
    if not isinstance(frame.metadata, dict):
        raise ValueError("Frame metadata must be a JSON dictionary")
    return dict(pixels=pixels.tobytes(order="C"), shape=pixels.shape, dtype=pixels.dtype.str,
                bit_depth=frame.bit_depth, camera_frame_id=frame.camera_frame_id,
                metadata=json_data(frame.metadata))


class Service:
    def __init__(self, plugin):
        self.plugin = plugin
        self.opened = False
        self.streaming = False
        self.source = None
        self.trigger = {}

    def snapshot(self):
        diagnostics = self.plugin.diagnostics()
        if not isinstance(diagnostics, dict):
            raise ValueError("diagnostics() must return a JSON dictionary")
        return dict(controls=controls_data(self.plugin.controls()), diagnostics=json_data(diagnostics),
                    trigger_configuration=self.trigger.get("settings", {}) if self.source else {},
                    trigger_input=self.trigger.get("input") if self.source else None)

    def stop(self):
        if self.streaming:
            self.plugin.stop()
            self.streaming = False

    def start(self):
        # Mark first so a partially started stream is stopped during cleanup.
        self.streaming = True
        self.plugin.start()

    def timing(self, source):
        before = controls_data(self.plugin.controls())
        diagnostics = self.plugin.diagnostics()
        geometry = {name: diagnostics[name] for name in ("image_width", "image_height", "image_bit_depth") if name in diagnostics}
        preserved = {}
        for name, c in before.items():
            if name == "fps":
                continue  # A hardware trigger may legitimately supersede preview FPS.
            auto = before.get({"exposure": "auto_exposure", "gain": "auto_gain"}.get(name), {})
            if name in STANDARD and auto.get("value", "Off") == "Off":
                preserved[name] = c["value"]
        self.stop()
        self.source, self.trigger = None, {}
        desired = trigger_data(self.plugin.configure_trigger(source or None), source)
        after = controls_data(self.plugin.controls())
        for name, value in preserved.items():
            if name not in after or after[name]["value"] != value:
                raise RuntimeError(f"Timing transition changed image setting '{name}'. Arduino was not started.")
        self.start()
        actual = trigger_data(self.plugin.read_trigger(), source)
        if actual != desired:
            raise RuntimeError("Trigger readback changed after starting acquisition. Arduino was not started.")
        after = controls_data(self.plugin.controls())
        for name, value in preserved.items():
            if name not in after or after[name]["value"] != value:
                raise RuntimeError(f"Starting acquisition changed image setting '{name}'. Arduino was not started.")
        diagnostics = self.plugin.diagnostics()
        if any(diagnostics.get(name) != value for name, value in geometry.items()):
            raise RuntimeError("Timing transition changed camera image geometry. Arduino was not started.")
        self.source, self.trigger = source, actual
        return self.snapshot()

    def dispatch(self, method, args):
        if method == "discover":
            devices = self.plugin.discover()
            ids, result = set(), []
            for device in devices:
                if (not isinstance(device, Device) or not isinstance(device.id, str) or not device.id
                        or device.id in ids or not isinstance(device.name, str) or not device.name
                        or not isinstance(device.vendor, str) or (device.serial is not None and not isinstance(device.serial, str))):
                    raise ValueError("Discovery must return Devices with unique nonempty IDs and names")
                ids.add(device.id)
                for mode in device.modes:
                    if (not isinstance(mode, Mode) or type(mode.width) is not int or type(mode.height) is not int
                            or mode.width <= 0 or mode.height <= 0 or not isinstance(mode.pixel_format, str) or not mode.pixel_format):
                        raise ValueError("Invalid discovered acquisition mode")
                result.append(json_data(asdict(device)))
            return result
        if method == "open":
            device, mode = args
            self.opened = True
            self.plugin.open(device, Mode(*mode) if mode else None)
            # Request the normal preview rate only when it is actually writable.
            controls = controls_data(self.plugin.controls())
            fps = controls.get("fps")
            if fps and fps["writable"]:
                try:
                    self.plugin.set_control("fps", 10.0)
                except Exception:
                    log.warning("Plugin camera could not accept 10 FPS preview", exc_info=True)
            return self.timing(None)
        if not self.opened:
            raise RuntimeError("Open a camera first")
        if method == "snapshot":
            return self.snapshot()
        if method == "timing":
            return self.timing(args[0])
        if method == "set":
            if self.source:
                raise RuntimeError("Stop recording before changing camera settings")
            name, value = args
            c = controls_data(self.plugin.controls()).get(name)
            if not c or not c["writable"]:
                raise ControlRejected(f"Camera control is unavailable or read-only: {name}")
            if c["choices"] and str(value) not in c["choices"]:
                raise ControlRejected(f"Unsupported choice for {name}: {value}")
            if c["value_type"] in {"float", "int"}:
                try:
                    value = float(value)
                except (ValueError, TypeError) as exc:
                    raise ControlRejected(f"{name} requires a number") from exc
                if not math.isfinite(value) or (c["limits_known"] and not c["minimum"] <= value <= c["maximum"]):
                    raise ControlRejected(f"Value outside the reported range for {name}")
                if c["value_type"] == "int":
                    if not value.is_integer():
                        raise ControlRejected(f"{name} requires an integer")
                    value = int(value)
            if c["requires_stop"]:
                self.stop()
            try:
                self.plugin.set_control(name, value)
            finally:
                if not self.streaming:
                    self.start()
            # Never accept a property change that silently enables external timing.
            trigger_data(self.plugin.read_trigger(), None)
            return self.snapshot()
        if method == "next":
            frame = self.plugin.next_frame(100)
            return frame_data(frame) if frame is not None else None
        raise ValueError(f"Unknown camera operation: {method}")

    def close(self):
        try:
            self.stop()
        finally:
            self.plugin.close()


def main(handle, manifest_path):
    # External Python also needs protection from the frozen parent's DLL directory.
    if os.name == "nt":
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    import faulthandler
    faulthandler.enable()
    logging.basicConfig(level=logging.INFO)
    if os.name == "nt":
        from multiprocessing.connection import PipeConnection as Connection
    else:
        from multiprocessing.connection import Connection
    connection = Connection(handle)
    service, dll_handles = None, []
    try:
        # A Windows venv can launch a second interpreter process. Identify the
        # real SDK owner before loading vendor code, then wait for host ownership.
        connection.send({"worker_pid": os.getpid(), "api_version": API_VERSION})
        if connection.recv() != "ready":
            return
        path = Path(manifest_path)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["api_version"] != API_VERSION:
            raise ValueError("Incompatible BURST camera plugin API")
        for directory in manifest.get("dll_directories", []):
            directory = str((path.parent / directory).resolve())
            if os.name == "nt":
                dll_handles.append(os.add_dll_directory(directory))
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        sys.path.insert(0, str(path.parent))
        module, name = manifest["entry_point"].split(":")
        plugin = getattr(importlib.import_module(module), name)()
        if not isinstance(plugin, CameraPlugin):
            raise TypeError("Plugin entry point must construct a CameraPlugin")
        service = Service(plugin)
        while True:
            method, args = connection.recv()
            if method == "close":
                break
            try:
                connection.send({"result": service.dispatch(method, args)})
            except ControlRejected as exc:
                connection.send({"error": str(exc), "fatal": False})
            except Exception as exc:
                # Only rejected values before native writes are recoverable. Any
                # SDK/state failure closes the stream rather than keeping unsafe
                # timing or image settings alive after a partially applied change.
                log.exception("Plugin operation %s failed", method)
                connection.send({"error": str(exc), "fatal": True})
                break
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        log.exception("Camera plugin helper failed")
        try:
            connection.send({"error": str(exc), "fatal": True})
        except (EOFError, OSError):
            pass
    finally:
        try:
            if service:
                service.close()
        finally:
            connection.close()
            for handle in dll_handles:
                handle.close()


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
