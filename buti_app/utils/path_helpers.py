# buti_app/utils/path_helpers.py

import os
import sys
from datetime import date
from pathlib import Path

import utils.config as config


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """Return absolute path to a bundled resource."""
    base = (
        os.path.join(sys._MEIPASS, "buti_app")
        if getattr(sys, "_MEIPASS", None)
        else BASE_DIR
    )
    return os.path.join(base, *parts)


def get_next_fill_folder() -> str:
    """
    Create (if needed) a folder at:
       BURST_ROOT/YYYY-MM-DD/FillN
    where YYYY-MM-DD = todayâ€™s date,
    and N = smallest positive integer so that â€œFillNâ€ does not yet exist.
    Returns the full path to the newly created â€œFillNâ€ folder.

    Example return: "/home/alice/Documents/BURST Results/2025-06-03/Fill1"
    """
    # 1) Todayâ€™s date folder: BURST_ROOT/YYYY-MM-DD
    today = date.today().isoformat()  # e.g. "2025-06-03"
    date_folder = os.path.join(config.BURST_ROOT, today)
    Path(date_folder).mkdir(parents=True, exist_ok=True)

    # 2) Look for existing â€œFillâ€ subfolders (Fill1, Fill2, â€¦)
    existing = []
    for entry in os.listdir(date_folder):
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
    new_fill_path = os.path.join(date_folder, new_fill_name)
    Path(new_fill_path).mkdir(parents=True, exist_ok=True)

    return new_fill_path


