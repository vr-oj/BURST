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

    x0 = max(0, min(frame_width, math.floor(left * frame_width)))
    y0 = max(0, min(frame_height, math.floor(top * frame_height)))
    x1 = max(0, min(frame_width, math.ceil(right * frame_width)))
    y1 = max(0, min(frame_height, math.ceil(bottom * frame_height)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


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
