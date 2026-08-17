"""Validation and transactional naming helpers for recording output."""

from __future__ import annotations

import os
import re
from pathlib import Path


_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def validate_path_component(value: str, *, label: str = "Name") -> str:
    """Return a trimmed Windows-safe filename component or raise ``ValueError``."""

    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty.")
    if cleaned in {".", ".."} or _INVALID_COMPONENT.search(cleaned):
        raise ValueError(f"{label} contains characters that are not allowed in filenames.")
    if cleaned.endswith((" ", ".")):
        raise ValueError(f"{label} cannot end with a space or period.")
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise ValueError(f"{label} uses a reserved Windows filename.")
    return cleaned


def recording_pair_paths(folder: str, base_name: str) -> tuple[str, str]:
    base_name = validate_path_component(base_name, label="Recording name")
    return (
        os.path.join(folder, f"{base_name}_force.csv"),
        os.path.join(folder, f"{base_name}_video.tif"),
    )


def find_recording_csv_for_tiff(tiff_path: str) -> str | None:
    """Return the most likely synchronized CSV beside ``tiff_path``.

    BURST's canonical pair is ``<name>_video.tif`` and
    ``<name>_force.csv``. Older same-stem pairs and folders containing a
    single CSV are also supported, while ambiguous folders are left for the
    caller to explain rather than silently pairing the wrong data.
    """

    tiff = Path(tiff_path)
    if tiff.suffix.lower() not in {".tif", ".tiff"}:
        return None
    try:
        csv_files = [path for path in tiff.parent.iterdir() if path.suffix.lower() == ".csv"]
    except OSError:
        return None

    by_name = {path.name.casefold(): path for path in csv_files}
    stem = tiff.stem
    candidate_names = []
    if stem.casefold().endswith("_video"):
        candidate_names.append(f"{stem[:-6]}_force.csv")
    candidate_names.append(f"{stem}.csv")

    for candidate_name in candidate_names:
        match = by_name.get(candidate_name.casefold())
        if match is not None:
            return str(match)
    if len(csv_files) == 1:
        return str(csv_files[0])
    return None


def rename_recording_pair(
    csv_path: str,
    tiff_path: str,
    base_name: str,
) -> tuple[str, str]:
    """Rename a synchronized pair without overwriting or leaving a half-renamed pair."""

    csv_source = Path(csv_path)
    tiff_source = Path(tiff_path)
    if csv_source.parent != tiff_source.parent:
        raise ValueError("The CSV and TIFF must be in the same folder.")
    if not csv_source.exists() or not tiff_source.exists():
        raise FileNotFoundError("Both recording files must exist before they can be renamed.")

    csv_target_s, tiff_target_s = recording_pair_paths(
        str(csv_source.parent), base_name
    )
    csv_target = Path(csv_target_s)
    tiff_target = Path(tiff_target_s)
    if csv_target == csv_source and tiff_target == tiff_source:
        return str(csv_source), str(tiff_source)

    for source, target in ((csv_source, csv_target), (tiff_source, tiff_target)):
        if target != source and target.exists():
            raise FileExistsError(f"{target.name} already exists.")

    csv_moved = False
    try:
        if csv_target != csv_source:
            csv_source.rename(csv_target)
            csv_moved = True
        if tiff_target != tiff_source:
            tiff_source.rename(tiff_target)
    except Exception:
        if csv_moved and csv_target.exists() and not csv_source.exists():
            csv_target.rename(csv_source)
        raise

    return str(csv_target), str(tiff_target)

