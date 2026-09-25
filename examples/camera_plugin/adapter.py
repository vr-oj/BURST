"""Working preview example. Replace simulated operations with your SDK calls.

This example deliberately refuses external triggering. Never claim a software
timer is an Arduino trigger or invent genuine camera frame IDs/timestamps.
"""
import time
import numpy as np
from burst_camera_plugin import CameraPlugin, Control, Device, Frame, Mode, TriggerState


class DemoCamera(CameraPlugin):
    def __init__(self):
        self.opened = self.streaming = False
        self.values = dict(exposure=10000.0, gain=1.0, fps=10.0)
        self.width, self.height = 320, 240
        self.next_due = 0.0

    def discover(self):
        return [Device("simulator", "SIMULATED camera (no hardware trigger)",
                       (Mode(320, 240, "Mono12"), Mode(640, 480, "Mono12")))]

    def open(self, device_id, mode):
        if device_id != "simulator":
            raise ValueError("Unknown demo camera")
        if mode is not None:
            if mode not in self.discover()[0].modes:
                raise ValueError("Unsupported mode")
            self.width, self.height = mode.width, mode.height
        self.opened = True

    def controls(self):
        return {
            "exposure": Control(self.values["exposure"], 100, 100000, 100, unit="us"),
            "gain": Control(self.values["gain"], 1, 8, 0.1, unit="camera units"),
            "fps": Control(self.values["fps"], 1, 30, 1, unit="Hz", requires_stop=True),
            "pixel_format": Control("Mono12", choices=("Mono12",), value_type="enum", writable=False),
            "vendor:Sensor temperature": Control(23.0, unit="°C", limits_known=False, writable=False),
        }

    def set_control(self, name, value):
        control = self.controls().get(name)
        if name not in self.values or not control.minimum <= float(value) <= control.maximum:
            raise ValueError("Unsupported setting")
        self.values[name] = float(value)

    def configure_trigger(self, source):
        if source:
            raise RuntimeError("The simulated example has no external trigger. Use a real SDK adapter for Arduino recording.")
        return self.read_trigger()

    def read_trigger(self):
        return TriggerState(False, settings={"Mode": "Internal"})

    def start(self):
        if not self.opened:
            raise RuntimeError("Camera is closed")
        self.streaming = True
        self.next_due = time.monotonic()

    def next_frame(self, timeout_ms):
        if not self.streaming:
            raise RuntimeError("Acquisition is stopped")
        delay = self.next_due - time.monotonic()
        if delay > 0:
            time.sleep(min(delay, timeout_ms / 1000))
        if time.monotonic() < self.next_due:
            return None
        self.next_due = time.monotonic() + 1 / self.values["fps"]
        gradient = np.linspace(0, 1600, self.width)
        pixels = np.tile(gradient, (self.height, 1)) * (self.values["exposure"] / 10000) * self.values["gain"]
        return Frame(np.clip(pixels, 0, 4095).astype(np.uint16), bit_depth=12,
                     metadata={"simulated": True})

    def stop(self):
        self.streaming = False

    def close(self):
        self.stop()
        self.opened = False

    def diagnostics(self):
        return {"simulated": True, "image_width": self.width, "image_height": self.height}
