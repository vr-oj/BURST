"""Optional path-only handoff from BURST to an installed BRAID application."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _first_existing(paths):
    for path in paths:
        candidate = Path(path).expanduser()
        if candidate.exists():
            return str(candidate)
    return None


def find_braid_application(configured_path: str | None = None) -> str | None:
    """Locate BRAID without making it a BURST dependency."""

    override = configured_path or os.environ.get("BRAID_APP_PATH")
    if override:
        found = _first_existing((override,))
        if found:
            return found

    on_path = shutil.which("BRAID") or shutil.which("BRAID.exe")
    if on_path:
        return on_path

    if sys.platform == "darwin":
        return _first_existing(
            (
                "/Applications/BRAID.app",
                Path.home() / "Applications" / "BRAID.app",
            )
        )

    if sys.platform.startswith("win"):
        search_roots = [
            Path(sys.executable).resolve().parent,
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "BRAID",
            Path(os.environ.get("PROGRAMFILES", "")) / "BRAID",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "BRAID",
        ]
        for root in search_roots:
            if not str(root) or not root.exists():
                continue
            matches = sorted(root.glob("BRAID*.exe"), reverse=True)
            if matches:
                return str(matches[0])
    return None


def braid_launch_command(
    application_path: str,
    recording_path: str,
) -> tuple[str, list[str]]:
    """Return the detached-process command for opening one recording in BRAID."""

    application = str(Path(application_path).expanduser())
    recording = str(Path(recording_path).expanduser())
    if sys.platform == "darwin" and application.lower().endswith(".app"):
        # A fresh instance guarantees the argument is delivered even if BRAID is
        # already running; macOS does not forward ``--args`` to an old process.
        return "open", ["-n", "-a", application, "--args", "--open", recording]
    return application, ["--open", recording]
