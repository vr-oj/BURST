"""Pure elapsed-time formatting shared by status displays."""

from __future__ import annotations


def format_elapsed_time(seconds: float | None) -> str:
    """Format elapsed seconds as ``MM:SS.hh`` using hundredths of a second.

    Minutes intentionally continue past 59 because device runs are discussed
    and labeled in minutes throughout the acquisition UI.
    """

    if seconds is None:
        return "\u2014"
    total_hundredths = max(0, int(round(float(seconds) * 100)))
    minutes, remainder = divmod(total_hundredths, 6000)
    whole_seconds, hundredths = divmod(remainder, 100)
    return f"{minutes:02d}:{whole_seconds:02d}.{hundredths:02d}"
