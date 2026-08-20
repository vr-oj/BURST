"""Crash-safe partial recording manifests, finalization, and recovery."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .recording_summary import RecordingSummary


MANIFEST_SCHEMA = "burst.run/v1"
PARTIAL_MANIFEST_NAME = "burst-run.json.partial"
FINAL_MANIFEST_NAME = "burst-run.json"


def _write_json(path: Path, data: dict) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def create_partial_manifest(
    output_dir: str,
    *,
    final_csv_name: str,
    final_tiff_name: str,
    partial_csv_name: str,
    partial_tiff_name: str,
    acquisition: dict | None = None,
) -> str:
    folder = Path(output_dir)
    manifest_path = folder / PARTIAL_MANIFEST_NAME
    _write_json(
        manifest_path,
        {
            "schema": MANIFEST_SCHEMA,
            "state": "recording",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                "csv": final_csv_name,
                "tiff": final_tiff_name,
                "partial_csv": partial_csv_name,
                "partial_tiff": partial_tiff_name,
            },
            "acquisition": acquisition or {},
        },
    )
    return str(manifest_path)


def discard_empty_partial_manifest(manifest_path: str | None) -> None:
    if not manifest_path:
        return
    try:
        Path(manifest_path).unlink(missing_ok=True)
    except OSError:
        pass


def finalize_partial_pair(
    partial_csv_path: str,
    partial_tiff_path: str,
    final_csv_path: str,
    final_tiff_path: str,
) -> tuple[str, str]:
    sources = (Path(partial_csv_path), Path(partial_tiff_path))
    targets = (Path(final_csv_path), Path(final_tiff_path))
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(f"Missing partial recording file: {source.name}")
    for target in targets:
        if target.exists():
            raise FileExistsError(f"Recording destination already exists: {target.name}")

    csv_moved = False
    try:
        sources[0].rename(targets[0])
        csv_moved = True
        sources[1].rename(targets[1])
    except Exception:
        if csv_moved and targets[0].exists() and not sources[0].exists():
            targets[0].rename(sources[0])
        raise
    return str(targets[0]), str(targets[1])


def complete_manifest(
    partial_manifest_path: str,
    summary: RecordingSummary,
    *,
    csv_path: str,
    tiff_path: str,
    state: str = "complete",
) -> str:
    partial_path = Path(partial_manifest_path)
    data = json.loads(partial_path.read_text(encoding="utf-8"))
    data["state"] = state
    data["completed_at"] = datetime.now(timezone.utc).isoformat()
    data["files"]["csv"] = Path(csv_path).name
    data["files"]["tiff"] = Path(tiff_path).name
    data["integrity"] = summary.to_dict()
    _write_json(partial_path, data)
    final_path = partial_path.with_name(FINAL_MANIFEST_NAME)
    os.replace(partial_path, final_path)
    return str(final_path)


def update_manifest_file_names(folder: str, csv_path: str, tiff_path: str) -> None:
    manifest_path = Path(folder) / FINAL_MANIFEST_NAME
    if not manifest_path.exists():
        return
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data.setdefault("files", {})["csv"] = Path(csv_path).name
    data["files"]["tiff"] = Path(tiff_path).name
    _write_json(manifest_path, data)


def find_recoverable_manifests(results_root: str) -> list[str]:
    root = Path(results_root)
    if not root.exists():
        return []
    manifests = []
    for directory, _subdirs, files in os.walk(root):
        if PARTIAL_MANIFEST_NAME in files:
            manifest = Path(directory) / PARTIAL_MANIFEST_NAME
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                file_names = data["files"]
                partial_paths = (
                    manifest.parent / file_names["partial_csv"],
                    manifest.parent / file_names["partial_tiff"],
                )
            except (OSError, KeyError, json.JSONDecodeError):
                manifests.append(str(manifest))
                continue
            if not any(path.exists() for path in partial_paths):
                discard_empty_partial_manifest(str(manifest))
                continue
            manifests.append(str(manifest))
    return sorted(manifests)


def _csv_stats(path: Path) -> tuple[int, float, int | None, int | None, list[str]]:
    samples = 0
    first_time = None
    last_time = None
    first_index = None
    last_index = None
    issues = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), start=2):
            try:
                time_s = float(row["time_s"])
                frame_index = int(float(row["frame_index"]))
            except (KeyError, TypeError, ValueError):
                if len(issues) < 5:
                    issues.append(
                        f"Skipped unreadable or incomplete CSV row {row_number}."
                    )
                continue
            if first_time is None:
                first_time = time_s
                first_index = frame_index
            elif (
                last_index is not None
                and frame_index != last_index + 1
                and len(issues) < 5
            ):
                issues.append(
                    f"Device frame index changed from {last_index} to {frame_index}."
                )
            last_time = time_s
            last_index = frame_index
            samples += 1
    duration = 0.0 if first_time is None else max(0.0, (last_time or first_time) - first_time)
    return samples, duration, first_index, last_index, issues


def inspect_recoverable_manifest(manifest_path: str) -> tuple[dict, RecordingSummary]:
    manifest = Path(manifest_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    files = data["files"]
    csv_path = manifest.parent / files["partial_csv"]
    tiff_path = manifest.parent / files["partial_tiff"]
    if not csv_path.exists() or not tiff_path.exists():
        raise FileNotFoundError("The interrupted recording is missing its CSV or TIFF file.")

    samples, duration, first_index, last_index, issues = _csv_stats(csv_path)
    try:
        import tifffile

        with tifffile.TiffFile(tiff_path) as recording:
            frames = len(recording.pages)
    except Exception as exc:
        raise OSError(f"The partial TIFF could not be read: {exc}") from exc

    if samples != frames:
        issues.append(f"Recovered counts differ: {samples} samples and {frames} frames.")
    issues.insert(0, "Recovered after an interrupted recording; review before analysis.")
    summary = RecordingSummary(
        status="recovered",
        samples_written=samples,
        frames_written=frames,
        duration_s=duration,
        csv_size_bytes=csv_path.stat().st_size,
        tiff_size_bytes=tiff_path.stat().st_size,
        pending_samples=max(0, samples - frames),
        first_frame_index=first_index,
        last_frame_index=last_index,
        issues=issues,
    )
    return data, summary


def recover_partial_recording(
    manifest_path: str,
) -> tuple[str, str, RecordingSummary]:
    data, summary = inspect_recoverable_manifest(manifest_path)
    manifest = Path(manifest_path)
    files = data["files"]
    csv_path, tiff_path = finalize_partial_pair(
        str(manifest.parent / files["partial_csv"]),
        str(manifest.parent / files["partial_tiff"]),
        str(manifest.parent / files["csv"]),
        str(manifest.parent / files["tiff"]),
    )
    summary.csv_size_bytes = Path(csv_path).stat().st_size
    summary.tiff_size_bytes = Path(tiff_path).stat().st_size
    try:
        complete_manifest(
            manifest_path,
            summary,
            csv_path=csv_path,
            tiff_path=tiff_path,
            state="recovered",
        )
    except Exception as exc:
        summary.issues.append(f"The recovery manifest could not be finalized: {exc}")
        discard_empty_partial_manifest(manifest_path)
    return csv_path, tiff_path, summary
