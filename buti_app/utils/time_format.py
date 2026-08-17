"""Pure elapsed-time formatting shared by status displays."""

from __future__ import annotations


def format_elapsed_time(seconds: float | None) -> str:
    if seconds is None:
        return "\u2014"
    total_tenths = max(0, int(round(float(seconds) * 10)))
    hours, remainder = divmod(total_tenths, 36000)
    minutes, remainder = divmod(remainder, 600)
    whole_seconds, tenths = divmod(remainder, 10)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{tenths}"
