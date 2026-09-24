"""Observation of the published BUTI v5 serial protocol (no settings RPC)."""
from collections import deque
import math

SUPPORTED_COMMANDS = frozenset({"G", "S"})
PROTOCOL_NOTE = (
    "The published BUTI v5.1/v5.2 firmware supports remote Start and Stop. "
    "It does not report its firmware version, delay or Capture selection, and has no "
    "commands to change experiment settings or acknowledge settings writes. "
    "Change those settings on the box. BURST follows the received data; observed "
    "rates are measurements, not a readback of the menu."
)
RATE_SETUP = (
    "On BUTI v5.1/v5.2, use Advanced settings → Delay (ms): 200 ms requests about "
    "5 force samples/second; 100 ms requests about 10. Capture Every requests an image "
    "for each sample. 1 in 5 requests one image for every five samples; None requests "
    "no images. Changing Capture does not lower the force sample rate. "
    "Actual timing depends on the box's workload. BURST measures it during a run. "
    "Older firmware menus may differ."
)


class BoxObservation:
    """Infer cadence only from device timestamps and counter transitions."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.last_time = self.last_counter = None
        self.intervals = deque(maxlen=50)
        self.divisors = deque(maxlen=5)
        self.rows = 0
        self.last_transition_row = None

    def observe(self, timestamp, counter):
        if not math.isfinite(timestamp) or timestamp < 0 or counter < 0:
            raise ValueError("Invalid device timestamp or trigger counter")
        previous_time, previous_counter = self.last_time, self.last_counter
        if previous_time is not None and timestamp <= previous_time:
            raise ValueError("Device time did not advance; the box may have reset or entered Step mode")
        if previous_counter is not None and counter < previous_counter:
            raise ValueError("Device trigger counter moved backwards; the box may have reset")
        self.rows += 1
        if (self.divisor and self.last_transition_row is not None
                and self.rows - self.last_transition_row > self.divisor):
            self.divisors.clear()
        if previous_time is not None:
            self.intervals.append(timestamp - previous_time)
        # The first row gives a baseline, not proof of a trigger during this run.
        triggered = previous_counter is not None and counter > previous_counter
        if triggered:
            if counter == previous_counter + 1 and self.last_transition_row is not None:
                self.divisors.append(self.rows - self.last_transition_row)
            else:
                self.divisors.clear()
            self.last_transition_row = self.rows
        self.last_time, self.last_counter = timestamp, counter
        return triggered, max(0, counter - previous_counter - 1) if triggered else 0

    @property
    def sample_hz(self):
        if len(self.intervals) < 3 or sum(self.intervals) < 1:
            return None
        return len(self.intervals) / sum(self.intervals)

    @property
    def divisor(self):
        if len(self.divisors) < 2 or len(set(self.divisors)) != 1:
            return None
        return self.divisors[-1]

    @property
    def image_hz(self):
        return self.sample_hz / self.divisor if self.sample_hz and self.divisor else None

    def snapshot(self):
        return {"sample_hz": self.sample_hz, "observed_capture_divisor": self.divisor,
                "image_hz": self.image_hz, "source": "observed_serial_data",
                "settings_readback_available": False}

    def description(self):
        sample = f"{self.sample_hz:.2f} samples/s" if self.sample_hz else "Measuring sample rate"
        capture = ("Every sample" if self.divisor == 1 else f"1 in {self.divisor}") if self.divisor else "Capture unknown (waiting for counter changes)"
        return f"Observed: {sample} · {capture}"
