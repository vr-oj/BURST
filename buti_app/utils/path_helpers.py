# buti_app/utils/path_helpers.py

import os
import sys
from datetime import date
from pathlib import Path

from . import config
from .recording_files import validate_path_component
from .recording_folders import is_recording_folder_name, next_run_folder_name


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
        and not is_recording_folder_name(entry.name)
    )


def get_next_run_folder(session_name: str) -> str:
    """
    Create (if needed) a folder at:
       BURST_ROOT/YYYY-MM-DD/Session Name/RunN
    where YYYY-MM-DD = todayâ€™s date,
    and N is the smallest positive integer not already used by a RunN or
    legacy FillN folder. Returns the full path to the new RunN folder.

    Example return:
    ``/home/alice/Documents/BURST Results/2025-06-03/Experiment A/Run1``
    """
    session_name = validate_path_component(session_name, label="Session name")
    session_folder = os.path.join(get_date_folder(), session_name)
    Path(session_folder).mkdir(parents=True, exist_ok=True)

    new_run_name = next_run_folder_name(os.listdir(session_folder))
    new_run_path = os.path.join(session_folder, new_run_name)
    Path(new_run_path).mkdir(parents=True, exist_ok=True)

    return new_run_path


def get_next_fill_folder(session_name: str) -> str:
    """Compatibility alias for integrations using the pre-Run function name."""

    return get_next_run_folder(session_name)
