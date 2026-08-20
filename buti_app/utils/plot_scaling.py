"""Pure helpers for calculating live-plot axis limits."""

import bisect
import math


def visible_force_limits(times, forces, xmin, xmax):
    """Return padded Y limits for finite samples inside an X-axis window."""

    if not times or not forces:
        return None

    xmin, xmax = sorted((xmin, xmax))
    start = bisect.bisect_left(times, xmin)
    stop = bisect.bisect_right(times, xmax)
    visible = [force for force in forces[start:stop] if math.isfinite(force)]
    if not visible:
        return None

    minimum = min(visible)
    maximum = max(visible)
    pad = max(abs(maximum - minimum) * 0.1, 2.0)
    return minimum - pad, maximum + pad
