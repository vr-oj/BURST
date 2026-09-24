"""Snapshot/command interface: only the acquisition thread touches native nodes."""
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Lock
import logging
import time

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraControl:
    value: float | str
    minimum: float = 0
    maximum: float = 0
    increment: float = 0
    choices: tuple[str, ...] = ()
    writable: bool = True
    unit: str = ""
    value_type: str = "float"
    limits_known: bool = True
    requires_stop: bool = False


class CameraController:
    """Exposure is µs, frame rate is Hz; gain uses its reported unit (legacy dB).

    Missing keys are unsupported. limits_known=False permits numeric entry
    without claiming a hardware range.

    Immutable snapshots never contain SDK objects. Writes are serviced in the
    acquisition worker; closing rejects pending commands before native cleanup.
    """

    def __init__(self):
        self._lock = Lock()
        self._commands = Queue()
        self._snapshot = {}
        self._active = False
        self._next_poll = 0.0
        self._last_error = ""
        self._diagnostics = {}

    def diagnostics(self):
        with self._lock:
            return dict(self._diagnostics)

    @staticmethod
    def _read_diagnostics(adapter):
        try:
            result = adapter.read_diagnostics()
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}

    def capabilities(self) -> dict[str, CameraControl]:
        with self._lock:
            return dict(self._snapshot)

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def set_value(self, name: str, value: float | str) -> None:
        with self._lock:
            control = self._snapshot.get(name)
            if not self._active or control is None or not control.writable:
                return
            self._commands.put((name, value))

    def open(self, adapter) -> None:
        with self._lock:
            self._snapshot = adapter.read_controls()
            self._diagnostics = self._read_diagnostics(adapter)
            self._active = True

    def service(self, adapter) -> None:
        changed = False
        while True:
            try:
                name, value = self._commands.get_nowait()
            except Empty:
                break
            try:
                adapter.set_value(name, value)
                with self._lock:
                    self._last_error = ""
            except Exception as exc:
                log.warning("Could not set camera %s: %s", name, exc)
                with self._lock:
                    self._last_error = f"Could not set {name}: {exc}"
            changed = True
        if changed or time.monotonic() >= self._next_poll:
            snapshot = adapter.read_controls()
            diagnostics = self._read_diagnostics(adapter)
            with self._lock:
                self._snapshot = snapshot
                self._diagnostics = diagnostics
            self._next_poll = time.monotonic() + 0.5

    def close(self) -> None:
        with self._lock:
            self._active = False
            self._snapshot = {}
            self._diagnostics = {}
            while not self._commands.empty():
                self._commands.get_nowait()


class EmptyControls:
    """Empty snapshot for a connection that reports no camera controls."""

    def read_controls(self):
        return {}


FLOAT_NODES = {"exposure": "ExposureTime", "gain": "Gain", "fps": "AcquisitionFrameRate"}
ENUM_NODES = {"auto_exposure": "ExposureAuto", "auto_gain": "GainAuto", "pixel_format": "PixelFormat"}


class IC4Controls:
    def __init__(self, grabber):
        self.grabber = grabber

    def read_controls(self):
        result = {}
        props = self.grabber.device_property_map
        for key, name in FLOAT_NODES.items():
            try:
                node = props.find_float(name)
                try:
                    # Reading increment for continuous properties logs native SDK
                    # errors even if Python catches the resulting exception.
                    mode = getattr(node, "increment_mode", None)
                    step = node.increment if getattr(mode, "name", None) == "INCREMENT" else 0
                except Exception:
                    step = 0
                result[key] = CameraControl(float(node.value), float(node.minimum),
                                            float(node.maximum), float(step),
                                            writable=not (getattr(node, "is_locked", False) or getattr(node, "is_readonly", False)))
            except Exception:
                pass
        for key, name in ENUM_NODES.items():
            try:
                node = props.find_enumeration(name)
                result[key] = CameraControl(str(node.value), choices=tuple(e.name for e in node.entries),
                                            writable=not (getattr(node, "is_locked", False) or getattr(node, "is_readonly", False)))
            except Exception:
                pass
        return result

    def set_value(self, name, value):
        props = self.grabber.device_property_map
        if name in FLOAT_NODES:
            props.find_float(FLOAT_NODES[name]).value = float(value)
        else:
            props.find_enumeration(ENUM_NODES[name]).value = value
