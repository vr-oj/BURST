"""Shared lossless frame transforms for live preview and TIFF recording."""

from __future__ import annotations

from typing import Any

from .roi import normalized_roi_to_bounds


def transform_qimage(
    qimage: Any,
    normalized_roi: tuple[float, float, float, float] | None = None,
    *,
    mirror_horizontal: bool = False,
    mirror_vertical: bool = False,
) -> tuple[Any, dict]:
    """Crop then mirror a QImage without resampling and return provenance."""

    source_width = int(qimage.width())
    source_height = int(qimage.height())
    bounds = normalized_roi_to_bounds(
        normalized_roi, (source_height, source_width)
    )
    transformed = qimage
    crop_metadata = None
    if bounds is not None:
        x0, y0, x1, y1 = bounds
        transformed = transformed.copy(x0, y0, x1 - x0, y1 - y0)
        crop_metadata = {
            "x": x0,
            "y": y0,
            "width": x1 - x0,
            "height": y1 - y0,
            "source_width": source_width,
            "source_height": source_height,
        }
    if mirror_horizontal or mirror_vertical:
        transformed = transformed.mirrored(
            bool(mirror_horizontal), bool(mirror_vertical)
        )
    metadata = {
        "source_width": source_width,
        "source_height": source_height,
        "mirror_horizontal": bool(mirror_horizontal),
        "mirror_vertical": bool(mirror_vertical),
    }
    if crop_metadata is not None:
        metadata["crop_roi"] = crop_metadata
    return transformed, metadata
