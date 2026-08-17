# buti_app/utils/path_helpers.py

import os
import sys
from datetime import date
from pathlib import Path

from . import config
from .recording_files import validate_path_component


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """Return absolute path to a bundled resource."""
    base = (
        os.path.join(sys._MEIPASS, "buti_app")
        if getattr(sys, "_MEIPASS", None)
        else BASE_DIR
    )
    return os.path.join(base, *parts)


def get_date_folder() -> str:
    """Return today's results folder, creating it when necessary."""

    date_folder = os.path.join(config.BURST_ROOT, date.today().isoformat())
    Path(date_folder).mkdir(parents=True, exist_ok=True)
    return date_folder


def list_session_names() -> list[str]:
    """List existing session folders under today's results folder."""

    return sorted(
        entry.name
        for entry in Path(get_date_folder()).iterdir()
        if entry.is_dir()
        and not (
            entry.name.startswith("Fill") and entry.name[4:].isdigit()
        )
    )


def get_next_fill_folder(session_name: str) -> str:
    """
    Create (if needed) a folder at:
       BURST_ROOT/YYYY-MM-DD/Session Name/FillN
    where YYYY-MM-DD = todayâ€™s date,
    and N = smallest positive integer so that â€œFillNâ€ does not yet exist.
    Returns the full path to the newly created â€œFillNâ€ folder.

    Example return:
    ``/home/alice/Documents/BURST Results/2025-06-03/Experiment A/Fill1``
    """
    session_name = validate_path_component(session_name, label="Session name")
    session_folder = os.path.join(get_date_folder(), session_name)
    Path(session_folder).mkdir(parents=True, exist_ok=True)

    # 2) Look for existing â€œFillâ€ subfolders (Fill1, Fill2, â€¦)
    existing = []
    for entry in os.listdir(session_folder):
        if entry.startswith("Fill"):
            suffix = entry[4:]
            if suffix.isdigit():
                existing.append(int(suffix))

    # 3) Pick the next unused integer
    n = 1
    while n in existing:
        n += 1

    # 4) Create the new FillN folder
    new_fill_name = f"Fill{n}"
    new_fill_path = os.path.join(session_folder, new_fill_name)
    Path(new_fill_path).mkdir(parents=True, exist_ok=True)

    return new_fill_path
