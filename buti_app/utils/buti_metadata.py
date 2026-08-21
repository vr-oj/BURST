"""Parse experiment settings printed by BUTI firmware serial headers."""

from __future__ import annotations

import re
from typing import Optional


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_COLUMN_HEADER = re.compile(
    r"^\s*time\s*,\s*frame\s*,\s*distance\s*,\s*cycle\s*,\s*force\s*$",
    re.IGNORECASE,
)
_SEPARATOR = re.compile(r"^\s*-{3,}\s*$")

BUTI_CSV_COLUMNS = (
    "experiment_type",
    "preload_mm",
    "deformation_mm",
    "deformation_percent",
    "steps",
    "rate_forward_mm_s",
    "rate_reverse_mm_s",
    "cycles_configured",
    "wire_diameter_mm",
    "constant_tension_mn",
)

BUTI_SETTINGS_TO_CSV = {
    "experiment_type": "experiment_type",
    "preload_mm": "preload_mm",
    "deformation_mm": "deformation_mm",
    "deformation_percent": "deformation_percent",
    "steps": "steps",
    "rate_forward_mm_s": "rate_forward_mm_s",
    "rate_reverse_mm_s": "rate_reverse_mm_s",
    "cycles": "cycles_configured",
    "wire_diameter_mm": "wire_diameter_mm",
    "constant_tension_mn": "constant_tension_mn",
}


def _number(value: str):
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


class ButiMetadataParser:
    """Accumulate one firmware header and return its typed settings snapshot.

    ``feed_line`` returns ``None`` for ordinary serial traffic, an empty dict
    for a recognized but incomplete header line, and a populated dict when the
    firmware's CSV column heading completes the settings header.
    """

    _VALUE_PATTERNS = (
        (
            "preload_mm",
            re.compile(
                rf"^\s*preload(?:\s*\(\s*mm\s*\))?\s*=\s*({_NUMBER})(?:\s*mm)?\s*$",
                re.IGNORECASE,
            ),
            float,
        ),
        (
            "deformation_mm",
            re.compile(
                rf"^\s*deform(?:\s*\(\s*mm\s*\))?\s*=\s*({_NUMBER})(?:\s*mm)?\s*$",
                re.IGNORECASE,
            ),
            float,
        ),
        (
            "deformation_percent",
            re.compile(
                rf"^\s*deform(?:\s*\(\s*%\s*\))?\s*=\s*({_NUMBER})(?:\s*%)?\s*$",
                re.IGNORECASE,
            ),
            _number,
        ),
        (
            "steps",
            re.compile(
                rf"^\s*(?:#\s*of\s*steps|steps\s*\(\s*#\s*\))\s*=\s*({_NUMBER})\s*$",
                re.IGNORECASE,
            ),
            _number,
        ),
        (
            "rate_forward_mm_s",
            re.compile(
                rf"^\s*rate\s+fwd(?:\s*\(\s*mm\s*/\s*sec\s*\))?\s*=\s*({_NUMBER})(?:\s*mm\s*/\s*sec)?\s*$",
                re.IGNORECASE,
            ),
            float,
        ),
        (
            "rate_reverse_mm_s",
            re.compile(
                rf"^\s*rate\s+rev(?:\s*\(\s*mm\s*/\s*sec\s*\))?\s*=\s*({_NUMBER})(?:\s*mm\s*/\s*sec)?\s*$",
                re.IGNORECASE,
            ),
            float,
        ),
        (
            "cycles",
            re.compile(
                rf"^\s*cycles(?:\s*\(\s*#\s*\))?\s*=\s*({_NUMBER})\s*$",
                re.IGNORECASE,
            ),
            _number,
        ),
        (
            "wire_diameter_mm",
            re.compile(
                rf"^\s*wire\s+diameter\s*=\s*({_NUMBER})(?:\s*mm)?\s*$",
                re.IGNORECASE,
            ),
            float,
        ),
        (
            "constant_tension_mn",
            re.compile(
                rf"^\s*constant\s+tension\s*=\s*({_NUMBER})(?:\s*mn)?\s*$",
                re.IGNORECASE,
            ),
            float,
        ),
    )

    _EXPERIMENT_TYPE = re.compile(
        r"^\s*experiment\s+type\s*:\s*(.+?)\s*$", re.IGNORECASE
    )
    _LEGACY_EXPERIMENT_TYPES = {
        "preconditioning": "Preconditioning",
        "constant velocity": "Constant Velocity",
        "stress relaxation": "Stress Relaxation",
        "constant tension": "Constant Tension",
    }

    def __init__(self):
        self._pending = {}

    def reset(self) -> None:
        self._pending.clear()

    def feed_line(self, line: str) -> Optional[dict]:
        """Consume one decoded serial line and return a completed snapshot."""

        if not isinstance(line, str):
            return None

        if _COLUMN_HEADER.fullmatch(line):
            snapshot = dict(self._pending)
            self.reset()
            return snapshot

        if _SEPARATOR.fullmatch(line):
            return {}

        experiment_match = self._EXPERIMENT_TYPE.fullmatch(line)
        if experiment_match:
            self._pending["experiment_type"] = experiment_match.group(1).strip()
            return {}

        legacy_experiment = self._LEGACY_EXPERIMENT_TYPES.get(line.strip().lower())
        if legacy_experiment is not None:
            self._pending["experiment_type"] = legacy_experiment
            return {}

        for key, pattern, converter in self._VALUE_PATTERNS:
            match = pattern.fullmatch(line)
            if match:
                self._pending[key] = converter(match.group(1))
                return {}

        return None
