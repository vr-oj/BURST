"""Track logical BURST data runs independently of the serial transport."""

from __future__ import annotations

from collections import deque


class SerialActivityTracker:
    """Detect run boundaries from valid-packet timing.

    The generous initial timeout covers the firmware's known five-second
    initialization cadence.  Once a cadence has been observed, the timeout
    tightens while retaining headroom for jitter.
    """

    def __init__(
        self,
        *,
        initial_timeout: float = 6.5,
        minimum_timeout: float = 2.0,
        maximum_timeout: float = 10.0,
        interval_multiplier: float = 1.5,
        history_size: int = 20,
    ) -> None:
        self.initial_timeout = float(initial_timeout)
        self.minimum_timeout = float(minimum_timeout)
        self.maximum_timeout = float(maximum_timeout)
        self.interval_multiplier = float(interval_multiplier)
        self._intervals: deque[float] = deque(maxlen=max(1, int(history_size)))
        self.active = False
        self.last_packet_at: float | None = None

    @property
    def timeout_seconds(self) -> float:
        if len(self._intervals) < 2:
            return self.initial_timeout
        learned = self.interval_multiplier * max(self._intervals)
        return max(self.minimum_timeout, min(self.maximum_timeout, learned))

    def note_packet(self, now: float) -> bool:
        """Record a valid packet and return ``True`` for a new run."""

        now = float(now)
        started = not self.active
        if started:
            self.active = True
            self._intervals.clear()
        elif self.last_packet_at is not None:
            interval = now - self.last_packet_at
            if interval >= 0:
                self._intervals.append(interval)
        self.last_packet_at = now
        return started

    def poll(self, now: float) -> bool:
        """Return ``True`` once when the current run has gone silent."""

        if not self.active or self.last_packet_at is None:
            return False
        if float(now) - self.last_packet_at <= self.timeout_seconds:
            return False
        self.mark_stopped()
        return True

    def mark_stopped(self) -> bool:
        """End the current run and return whether one was active."""

        was_active = self.active
        self.active = False
        self.last_packet_at = None
        self._intervals.clear()
        return was_active

    def reset(self) -> None:
        self.mark_stopped()

