"""Conservative arrival-rate checks; these do not establish exposure synchronization."""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RateCheck:
    passed: bool
    detail: str


class CameraRateMonitor:
    def __init__(self):
        self.times = deque(maxlen=1000)

    def reset(self):
        self.times.clear()

    def observe(self, now):
        self.times.append(now)
        self._prune(now)

    def _prune(self, now):
        while self.times and now - self.times[0] > 5:
            self.times.popleft()

    def fps(self, now):
        self._prune(now)
        if len(self.times) < 2 or self.times[-1] - self.times[0] < 3:
            return None
        # Include time since the last image so a stalled stream cannot look healthy.
        return (len(self.times) - 1) / max(now - self.times[0], 0.001)


def check_camera_rate(measured, configured=None, maximum=None, target=10.0):
    for value, label in ((maximum, "Camera reports a maximum of"), (configured, "Camera is set to")):
        if value is not None and math.isfinite(value) and value < target * 0.995:
            return RateCheck(False, f"{label} {value:.2f} FPS; recording requires {target:g} FPS.")
    if measured is None or not math.isfinite(measured):
        return RateCheck(False, "Measuring camera rate. Let the preview run for at least 5 seconds, then retry.")
    if measured < target * 0.95:
        return RateCheck(False, f"Receiving {measured:.2f} FPS; recording requires approximately {target:g} FPS.")
    return RateCheck(True, f"Receiving {measured:.2f} FPS; target {target:g} FPS (5% tolerance). Timing synchronization not verified.")


RATE_GUIDANCE = (
    "BURST requests 10 FPS for preview by default. Recording follows changes in the "
    "Arduino trigger counter and keeps every force sample. The first sample establishes "
    "the counter baseline; no image is assigned to that row because its trigger phase is unknown. "
    "A camera delivering 6.8 FPS can keep up with about 5 requested images/second.\n\n"
    "For more camera throughput, reduce acquisition resolution, use Mono8, shorten exposure "
    "with more light, or check USB bandwidth. The recording ROI only crops saved images.\n\n"
    "BURST cannot read or change the box's Capture/Delay menu settings remotely. "
    "It observes counter changes during a run and stops if requested images fall behind. "
    "Software image pairing is not verified hardware synchronization."
)
