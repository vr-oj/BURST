"""BURST camera plugin API v1. No Qt or BURST application imports.

Plugins run in their own Python environment. See docs/camera-plugins.md for the
contract, installation and validation checklist. All SDK calls use one worker.
"""
from dataclasses import dataclass, field
from typing import Any

API_VERSION = 1


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    pixel_format: str


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    modes: tuple[Mode, ...] = ()
    vendor: str = ""
    serial: str | None = None


@dataclass(frozen=True)
class Control:
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


@dataclass(frozen=True)
class TriggerState:
    external: bool = False
    input: str | None = None
    settings: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Frame:
    pixels: Any  # numpy uint8/uint16 mono, or uint8 RGB (height, width, 3)
    bit_depth: int = 8
    camera_frame_id: int | None = None
    metadata: dict = field(default_factory=dict)


class CameraPlugin:
    """Implement in the lab's SDK adapter; never send Arduino commands here.

    open() may partly initialize before failing: close() must tolerate that.
    start() must discard old queued frames before starting a new sequence.
    next_frame() returns None on an ordinary timeout; overflow is an error.
    stop() must return even when an externally triggered camera has no pulses.
    configure_trigger()/read_trigger() describe actual per-frame triggering.
    """
    def discover(self) -> list[Device]:
        raise NotImplementedError

    def open(self, device_id: str, mode: Mode | None) -> None:
        raise NotImplementedError

    def controls(self) -> dict[str, Control]:
        raise NotImplementedError

    def set_control(self, name: str, value: float | str) -> None:
        raise NotImplementedError

    def configure_trigger(self, source: str | None) -> TriggerState:
        raise NotImplementedError

    def read_trigger(self) -> TriggerState:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    def next_frame(self, timeout_ms: int) -> Frame | None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def diagnostics(self) -> dict:
        return {}
