"""Silent pre-recording readiness checks."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreflightCheck:
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


def run_recording_preflight(
    *,
    serial_ready: bool,
    camera_ready: bool,
    camera_frame_age_s: float | None,
    session_name: str | None,
    device_run_active: bool,
    results_root: str,
    minimum_free_gb: float,
    maximum_camera_frame_age_s: float = 3.0,
) -> PreflightReport:
    """Check recording prerequisites without involving UI code."""

    checks = [
        PreflightCheck(
            "BUTI Arduino Box",
            bool(serial_ready),
            "Connected and ready" if serial_ready else "Not connected",
        ),
        PreflightCheck(
            "Camera",
            bool(camera_ready),
            "Camera thread is running" if camera_ready else "Camera is not running",
        ),
        PreflightCheck(
            "Camera frames",
            camera_frame_age_s is not None
            and camera_frame_age_s <= maximum_camera_frame_age_s,
            (
                f"Latest frame received {camera_frame_age_s:.1f} seconds ago"
                if camera_frame_age_s is not None
                else "No camera frame has been received"
            ),
        ),
        PreflightCheck(
            "Recording session",
            bool(session_name),
            f"Using {session_name}" if session_name else "No session selected",
        ),
        PreflightCheck(
            "Device state",
            not device_run_active,
            "Ready" if not device_run_active else "A manual device run is active",
        ),
    ]

    root = Path(results_root)
    writable = False
    writable_detail = "Results folder is not writable"
    try:
        root.mkdir(parents=True, exist_ok=True)
        descriptor, probe_path = tempfile.mkstemp(prefix=".burst-preflight-", dir=root)
        os.close(descriptor)
        os.unlink(probe_path)
        writable = True
        writable_detail = f"Writable: {root}"
    except OSError as exc:
        writable_detail = f"Cannot write to {root}: {exc}"
    checks.append(PreflightCheck("Results folder", writable, writable_detail))

    disk_ready = False
    disk_detail = "Disk space could not be checked"
    if writable:
        try:
            _total, _used, free = shutil.disk_usage(root)
            free_gb = free / 1024**3
            disk_ready = free_gb >= minimum_free_gb
            disk_detail = (
                f"{free_gb:.1f} GB available; {minimum_free_gb:g} GB required"
            )
        except OSError as exc:
            disk_detail = f"Unable to check disk space: {exc}"
    checks.append(PreflightCheck("Disk space", disk_ready, disk_detail))

    return PreflightReport(tuple(checks))
