# File: buti_app/utils/config.py

"""Central configuration for the BURST application."""

import os
import sys
from pathlib import Path

from PyQt5.QtCore import QDir, QStandardPaths

from utils.version import APP_VERSION

DOCUMENTS_DIR = os.path.join(os.path.expanduser("~"), "Documents")

DEFAULT_RESULTS_DIR = os.path.join(DOCUMENTS_DIR, "BURST Results")
BURST_RESULTS_DIR = os.environ.get("BURST_RESULTS_DIR") or os.environ.get(
    "BUTI_RESULTS_DIR",
    DEFAULT_RESULTS_DIR,
)
BURST_ROOT = BURST_RESULTS_DIR
BUTI_RESULTS_DIR = BURST_RESULTS_DIR  # Backwards-compatible alias
BUTI_ROOT = BURST_ROOT  # Backwards-compatible alias
Path(BURST_RESULTS_DIR).mkdir(parents=True, exist_ok=True)


def set_results_dir(path: str) -> None:
    """Update BURST/BUTI results directory settings and ensure the folder exists."""
    global BURST_RESULTS_DIR, BURST_ROOT, BUTI_RESULTS_DIR, BUTI_ROOT
    BURST_RESULTS_DIR = path
    BURST_ROOT = path
    BUTI_RESULTS_DIR = path
    BUTI_ROOT = path
    os.environ["BURST_RESULTS_DIR"] = path
    os.environ["BUTI_RESULTS_DIR"] = path
    Path(path).mkdir(parents=True, exist_ok=True)


DEFAULT_VIDEO_EXTENSION = "tif"
DEFAULT_VIDEO_CODEC = None  # Not used when recording to TIFF
SUPPORTED_FORMATS = ["tif"]
DEFAULT_FPS = 10
DEFAULT_CAMERA_INDEX = 0  # Default device index

# Frame size fallback (actual size will be queried from camera at runtime)
DEFAULT_FRAME_SIZE = (640, 480)  # (width, height)

# Minimum free disk space in gigabytes required before starting a recording
MIN_FREE_SPACE_GB = 30


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEV_MODE = _env_flag("BURST_DEV_MODE", False) or _env_flag("BUTI_DEV_MODE", False)

_camera_backend_env = (
    os.environ.get("BURST_CAMERA_BACKEND") or os.environ.get("BUTI_CAMERA_BACKEND")
)
if _camera_backend_env:
    CAMERA_BACKEND = _camera_backend_env.strip().lower()
else:
    CAMERA_BACKEND = "ic4" if sys.platform.startswith("win") else "opencv"


DEFAULT_SERIAL_BAUD_RATE = 460800

_SERIAL_TERMINATOR_ENV = (
    os.environ.get("BURST_SERIAL_TERMINATOR")
    or os.environ.get("BUTI_SERIAL_TERMINATOR")
)
if _SERIAL_TERMINATOR_ENV is None:
    SERIAL_COMMAND_TERMINATOR = b"\n"  # BUTI Arduino Box firmware sends lines terminated with newline
else:
    if _SERIAL_TERMINATOR_ENV.lower() == "none":
        SERIAL_COMMAND_TERMINATOR = b""
    else:
        SERIAL_COMMAND_TERMINATOR = (
            _SERIAL_TERMINATOR_ENV.encode("utf-8")
            .decode("unicode_escape")
            .encode("latin1")
        )


def _float_from_env(name: str, default: float | None) -> float | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


SERIAL_PORT_TIMEOUT_S = _float_from_env("BURST_SERIAL_TIMEOUT", None)
if SERIAL_PORT_TIMEOUT_S is None:
    SERIAL_PORT_TIMEOUT_S = _float_from_env("BUTI_SERIAL_TIMEOUT", 1.0)

SERIAL_PORT_WRITE_TIMEOUT_S = _float_from_env("BURST_SERIAL_WRITE_TIMEOUT", None)
if SERIAL_PORT_WRITE_TIMEOUT_S is None:
    SERIAL_PORT_WRITE_TIMEOUT_S = _float_from_env("BUTI_SERIAL_WRITE_TIMEOUT", None)

# Single-character commands supported by the BURST firmware
SERIAL_CMD_START = "G"
SERIAL_CMD_STOP = "S"
SERIAL_CMD_HOME = "H"
SERIAL_CMD_RESET = "R"
SERIAL_CMD_STEP = "Z"

SERIAL_COMMANDS = {
    "start": SERIAL_CMD_START,
    "stop": SERIAL_CMD_STOP,
    "home": SERIAL_CMD_HOME,
    "reset": SERIAL_CMD_RESET,
    "step": SERIAL_CMD_STEP,
}

APP_NAME = "BURST"
RELEASES_URL = "https://github.com/vr-oj/BURST/releases/latest"
ABOUT_TEXT = f"""
<strong>{APP_NAME} v{APP_VERSION}</strong>
<p>BURST stands for BUTI Uniaxial Recording of Strain &amp; Tension.</p>
<p>This application displays a live camera feed and force data from the BUTI Arduino Box, live plots force vs. time, and records the synchronized data into a high-resolution TIFF stack (with embedded metadata) and a synchronized CSV log.</p>
<p>Experiment control (start/stop) can be triggered directly from this application.</p>
"""

LOG_LEVEL = "DEBUG"  # DEBUG, INFO, WARNING, ERROR

PLOT_MAX_POINTS = 1000  # Max points to keep in live plot
PLOT_DEFAULT_Y_MIN = -5
PLOT_DEFAULT_Y_MAX = 30  # Typical force range in mN

# User-writable directory for storing camera profiles
APP_CONFIG_DIR = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
CAMERA_PROFILES_DIR = os.path.join(APP_CONFIG_DIR, "camera_profiles")
QDir().mkpath(CAMERA_PROFILES_DIR)

# Diagnostic logs belong to the application, not to an experiment's results.
# Keep them in a clearly named, user-local folder so they are easy to find and
# send when troubleshooting without mixing them into recorded data.
DIAGNOSTIC_LOG_DIR = os.path.join(APP_CONFIG_DIR, APP_NAME, "Logs")
DIAGNOSTIC_LOG_PATH = os.path.join(DIAGNOSTIC_LOG_DIR, "BURST-diagnostic.log")
