"""Pure helpers shared by playback ROI operations."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence


def normalized_roi_to_bounds(
    roi: tuple[float, float, float, float] | None,
    frame_shape: Sequence[int],
) -> tuple[int, int, int, int] | None:
    """Map a normalized ROI to clamped source-pixel slice bounds.

    ``roi`` is ``(left, top, right, bottom)`` in the range 0..1.  Returned
    right and bottom coordinates are exclusive so the tuple can be used
    directly for NumPy slicing.
    """

    if roi is None or len(frame_shape) < 2:
        return None

    frame_height, frame_width = int(frame_shape[0]), int(frame_shape[1])
    if frame_width <= 0 or frame_height <= 0:
        return None

    left, right = sorted((float(roi[0]), float(roi[2])))
    top, bottom = sorted((float(roi[1]), float(roi[3])))
    left = max(0.0, min(1.0, left))
    right = max(0.0, min(1.0, right))
    top = max(0.0, min(1.0, top))
    bottom = max(0.0, min(1.0, bottom))
    if right <= left or bottom <= top:
        return None

    def snap_pixel(value: float) -> float:
        nearest = round(value)
        return float(nearest) if abs(value - nearest) < 1e-9 else value

    x0 = max(0, min(frame_width, math.floor(snap_pixel(left * frame_width))))
    y0 = max(0, min(frame_height, math.floor(snap_pixel(top * frame_height))))
    x1 = max(0, min(frame_width, math.ceil(snap_pixel(right * frame_width))))
    y1 = max(0, min(frame_height, math.ceil(snap_pixel(bottom * frame_height))))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def pixel_roi_to_bounds(
    x: int,
    y: int,
    width: int,
    height: int,
    frame_shape: Sequence[int],
) -> tuple[int, int, int, int]:
    """Validate a source-pixel ROI and return exclusive slice bounds."""

    if len(frame_shape) < 2:
        raise ValueError("The source frame dimensions are unavailable.")

    frame_height, frame_width = int(frame_shape[0]), int(frame_shape[1])
    x, y, width, height = int(x), int(y), int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("ROI width and height must be at least 1 pixel.")
    if x < 0 or y < 0:
        raise ValueError("ROI X and Y must not be negative.")
    if x + width > frame_width or y + height > frame_height:
        raise ValueError(
            f"ROI ({x}, {y}, {width}×{height}) does not fit inside the "
            f"{frame_width}×{frame_height} source frame."
        )
    return x, y, x + width, y + height


def bounds_to_normalized_roi(
    bounds: tuple[int, int, int, int],
    frame_shape: Sequence[int],
) -> tuple[float, float, float, float]:
    """Convert validated source-pixel bounds to normalized coordinates."""

    x0, y0, x1, y1 = bounds
    validated = pixel_roi_to_bounds(
        x0,
        y0,
        x1 - x0,
        y1 - y0,
        frame_shape,
    )
    frame_height, frame_width = int(frame_shape[0]), int(frame_shape[1])
    x0, y0, x1, y1 = validated
    return (
        x0 / frame_width,
        y0 / frame_height,
        x1 / frame_width,
        y1 / frame_height,
    )


def add_crop_to_description(
    description: str | None,
    bounds: tuple[int, int, int, int],
    source_shape: Sequence[int],
) -> str | None:
    """Add crop provenance to a BURST JSON TIFF description.

    Non-JSON descriptions are returned unchanged so third-party TIFF metadata
    is not replaced with a different format.
    """

    if description:
        try:
            metadata = json.loads(description)
        except (TypeError, ValueError, json.JSONDecodeError):
            return description
        if not isinstance(metadata, dict):
            return description
    else:
        metadata = {}

    x0, y0, x1, y1 = bounds
    metadata["crop_roi"] = {
        "x": x0,
        "y": y0,
        "width": x1 - x0,
        "height": y1 - y0,
        "source_width": int(source_shape[1]),
        "source_height": int(source_shape[0]),
    }
    return json.dumps(metadata)
