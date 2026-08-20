"""Generate BURST's synthesized recording-completion WAV assets."""

import math
import wave
from array import array
from pathlib import Path


SAMPLE_RATE = 44_100
OUTPUT_DIR = Path(__file__).parents[1] / "buti_app" / "ui" / "sounds"


SOUNDS = {
    "gentle_chime.wav": {
        "duration": 0.82,
        "notes": (
            (0.00, 659.25, 0.58, 0.34, ((1.0, 1.0), (2.0, 0.13), (3.0, 0.04))),
            (0.14, 987.77, 0.66, 0.30, ((1.0, 1.0), (2.0, 0.11), (3.0, 0.03))),
        ),
    },
    "soft_bell.wav": {
        "duration": 0.88,
        "notes": (
            (0.00, 783.99, 0.83, 0.30, ((1.0, 1.0), (2.01, 0.12), (3.97, 0.035))),
            (0.10, 1174.66, 0.72, 0.22, ((1.0, 1.0), (2.01, 0.09), (3.97, 0.025))),
        ),
    },
    "warm_chime.wav": {
        "duration": 0.86,
        "notes": (
            (0.00, 523.25, 0.72, 0.34, ((1.0, 1.0), (2.0, 0.10), (3.0, 0.025))),
            (0.13, 783.99, 0.71, 0.28, ((1.0, 1.0), (2.0, 0.09), (3.0, 0.02))),
        ),
    },
}


def _note_sample(local_time, duration, frequency, partials):
    if local_time < 0 or local_time >= duration:
        return 0.0

    attack = min(local_time / 0.012, 1.0)
    attack = attack * attack * (3.0 - 2.0 * attack)
    decay = math.exp(-4.2 * local_time / duration)
    release = min((duration - local_time) / 0.07, 1.0)
    release = release * release * (3.0 - 2.0 * release)
    tone = sum(
        weight * math.sin(2.0 * math.pi * frequency * ratio * local_time)
        for ratio, weight in partials
    )
    return attack * decay * release * tone


def _render_sound(duration, notes):
    samples = array("h")
    for index in range(round(duration * SAMPLE_RATE)):
        time_s = index / SAMPLE_RATE
        sample = sum(
            amplitude
            * _note_sample(time_s - start, note_duration, frequency, partials)
            for start, frequency, note_duration, amplitude, partials in notes
        )
        sample = math.tanh(sample * 1.15) * 0.82
        samples.append(round(max(-1.0, min(1.0, sample)) * 32767))
    return samples


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, definition in SOUNDS.items():
        samples = _render_sound(definition["duration"], definition["notes"])
        with wave.open(str(OUTPUT_DIR / filename), "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(2)
            sound.setframerate(SAMPLE_RATE)
            sound.writeframes(samples.tobytes())


if __name__ == "__main__":
    main()
