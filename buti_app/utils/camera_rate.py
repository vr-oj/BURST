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
    "BURST expects 10 camera frames per second to keep up with the normal force-sample rate.\n\n"
    "Options:\n"
    "• Request 10 FPS, then allow 5 seconds to measure again.\n"
    "• Stop the camera and choose a smaller acquisition resolution or Mono8. "
    "The recording ROI only crops saved images; it does not reduce camera transfer bandwidth.\n"
    "• Turn off automatic exposure and try 10 ms exposure with more light.\n"
    "• Use the camera's recommended cable and a direct USB 3 port; avoid shared hubs.\n"
    "• Check bandwidth/transfer limits in the vendor's camera utility, with BURST's camera stopped.\n\n"
    "If the camera still cannot sustain 10 FPS, use another camera or an independently validated "
    "acquisition setup. BURST cannot lower the Arduino's sample rate from this dialog. "
    "A passing rate check does not prove hardware synchronization. FLIR acquisition currently "
    "runs with triggering off. A trigger cable alone does not enable synchronization; "
    "it requires compatible wiring and a configured, validated camera trigger mode."
)
