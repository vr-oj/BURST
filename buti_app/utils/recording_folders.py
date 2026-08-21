"""Naming helpers for numbered recording-run folders."""

RUN_FOLDER_PREFIX = "Run"
LEGACY_RUN_FOLDER_PREFIXES = ("Fill",)


def recording_folder_number(name: str):
    """Return the numeric suffix for current or legacy run-folder names."""

    for prefix in (RUN_FOLDER_PREFIX, *LEGACY_RUN_FOLDER_PREFIXES):
        if name.startswith(prefix):
            suffix = name[len(prefix) :]
            if suffix.isdigit():
                return int(suffix)
    return None


def is_recording_folder_name(name: str) -> bool:
    return recording_folder_number(name) is not None


def next_run_folder_name(existing_names) -> str:
    """Choose the first RunN number unused by either RunN or legacy FillN."""

    existing_numbers = {
        number
        for name in existing_names
        if (number := recording_folder_number(name)) is not None
    }
    number = 1
    while number in existing_numbers:
        number += 1
    return f"{RUN_FOLDER_PREFIX}{number}"
