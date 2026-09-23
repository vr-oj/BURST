"""Owned camera pixels for recording, separate from the 8-bit preview."""
from dataclasses import dataclass, field
import time
import numpy as np


@dataclass(frozen=True)
class FrameData:
    pixels: np.ndarray
    received_monotonic: float = field(default_factory=time.monotonic)
    pixel_format: str = "unknown"
    native_depth_preserved: bool = True
    camera_frame_id: int | None = None

    @classmethod
    def copy(cls, pixels, **kwargs):
        return cls(np.array(pixels, copy=True, order="C"), **kwargs)
