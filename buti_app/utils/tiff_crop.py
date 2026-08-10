"""Atomic, streaming crop export for TIFF frame stacks."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence

import numpy as np
from tifffile import TiffFile, TiffWriter

from .roi import add_crop_to_description


class CropCanceled(Exception):
    """Raised when a TIFF crop operation is canceled before completion."""


def export_cropped_tiff(
    source_path: str,
    output_path: str,
    bounds: tuple[int, int, int, int],
    source_shape: Sequence[int],
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """Crop every page of ``source_path`` into ``output_path``.

    The source is read one page at a time. Output is first written beside the
    requested destination and atomically installed only after all pages have
    succeeded, so a failure or cancellation cannot leave a partial result at
    the requested filename. The returned integer is the number of frames.
    """

    expected_shape = (int(source_shape[0]), int(source_shape[1]))
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= expected_shape[1]):
        raise ValueError("The ROI horizontal bounds are outside the source frame.")
    if not (0 <= y0 < y1 <= expected_shape[0]):
        raise ValueError("The ROI vertical bounds are outside the source frame.")

    source_path = os.path.abspath(source_path)
    output_path = os.path.abspath(output_path)
    source_key = os.path.normcase(os.path.realpath(source_path))
    output_key = os.path.normcase(os.path.realpath(output_path))
    same_file = source_key == output_key
    if not same_file and os.path.exists(output_path):
        try:
            same_file = os.path.samefile(source_path, output_path)
        except OSError:
            pass
    if same_file:
        raise ValueError("The cropped TIFF cannot replace the source recording.")

    output_dir = os.path.dirname(output_path)
    temp_file = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=".burst-roi-",
        suffix=".tif",
        dir=output_dir,
        delete=False,
    )
    temp_path = temp_file.name
    temp_file.close()

    try:
        frame_count = 0
        with TiffFile(source_path) as source_tiff:
            total = len(source_tiff.pages)
            if total == 0:
                raise ValueError("The source TIFF does not contain any frames.")

            with TiffWriter(temp_path, bigtiff=True) as output_tiff:
                for index, page in enumerate(source_tiff.pages):
                    if should_cancel is not None and should_cancel():
                        raise CropCanceled()

                    frame = page.asarray()
                    if frame.ndim != 2:
                        raise ValueError(
                            "ROI stack export currently requires grayscale frames."
                        )
                    if tuple(frame.shape[:2]) != expected_shape:
                        raise ValueError(
                            "Frame dimensions changed within the TIFF stack; "
                            "a fixed ROI cannot be applied safely."
                        )

                    cropped = np.ascontiguousarray(frame[y0:y1, x0:x1])
                    description = add_crop_to_description(
                        page.description,
                        bounds,
                        expected_shape,
                    )
                    photometric = (
                        page.photometric
                        if page.photometric is not None
                        else "minisblack"
                    )
                    output_tiff.write(
                        cropped,
                        photometric=photometric,
                        description=description,
                        metadata=None,
                    )
                    frame_count += 1
                    if on_progress is not None:
                        on_progress(index + 1, total)

        if should_cancel is not None and should_cancel():
            raise CropCanceled()

        os.replace(temp_path, output_path)
        temp_path = None
        return frame_count
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
