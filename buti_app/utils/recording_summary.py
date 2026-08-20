"""Structured post-recording integrity information and display formatting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class RecordingSummary:
    status: str
    samples_written: int
    frames_written: int
    duration_s: float
    csv_size_bytes: int = 0
    tiff_size_bytes: int = 0
    pending_samples: int = 0
    first_frame_index: int | None = None
    last_frame_index: int | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def checks_passed(self) -> bool:
        return self.status == "passed"

    @property
    def status_title(self) -> str:
        if self.status == "passed":
            return "Capture checks passed"
        if self.status == "recovered":
            return "Interrupted recording recovered"
        return "Recording needs review"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RecordingSummary":
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes, remaining = divmod(seconds, 60.0)
    return f"{int(minutes):02d}:{remaining:05.2f}"


def format_bytes(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            decimals = 0 if unit == "B" else 1
            return f"{value:.{decimals}f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"
