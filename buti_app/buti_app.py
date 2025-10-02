# File: buti_app/buti_app.py

import sys
import os
import re
import traceback
import logging
try:
    import imagingcontrol4 as ic4  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    ic4 = None

from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication
from PyQt5.QtGui import QIcon, QSurfaceFormat, QPalette, QColor
import utils.config as config
from utils.config import APP_NAME, APP_VERSION as CONFIG_APP_VERSION
from utils.path_helpers import resource_path

import matplotlib

logging.getLogger("matplotlib").setLevel(logging.INFO)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)

# ------------------------------
# Configure Python-level logging
# ------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s",
)
log = logging.getLogger(__name__)

# A separate module-level logger for setup steps
module_log = logging.getLogger("burst_app.setup")
if not module_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s"
    )
    handler.setFormatter(formatter)
    module_log.addHandler(handler)
    module_log.setLevel(logging.INFO)


# === load_app_setting / save_app_setting stubs if missing ===
try:
    from utils.app_settings import (
        load_app_setting,
        save_app_setting,
        SETTING_RESULTS_DIR,
    )

    APP_SETTINGS_AVAILABLE = True
except ImportError:
    APP_SETTINGS_AVAILABLE = False

    def load_app_setting(key, default=None):
        return default

    def save_app_setting(key, value):
        pass

    SETTING_RESULTS_DIR = None

    module_log.warning(
        "utils.app_settings not found. Persistent settings will not work."
    )


def apply_dark_theme(app):
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)


def load_processed_qss(path):
    """
    If you use “@variable: #RRGGBB;” in your QSS, this helper expands them.
    Returns the final QSS string or "" on error.
    """
    var_re = re.compile(r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});")
    vars_map, lines = {}, []
    try:
        with open(path, "r") as f:
            for line in f:
                m = var_re.match(line)
                if m:
                    vars_map[m.group(1)] = m.group(2)
                else:
                    for name, val in vars_map.items():
                        line = line.replace(f"@{name}", val)
                    lines.append(line)
        return "".join(lines)
    except Exception as e:
        log.error(f"Error loading/processing QSS file {path}: {e}")
        return ""


def main_app_entry():
    # ─── Set Default OpenGL 3.3 Core Profile ─────────────────────────────
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setVersion(3, 3)
    QSurfaceFormat.setDefaultFormat(fmt)
    log.info(
        "Attempted to set default QSurfaceFormat to OpenGL 3.3 Core Profile globally."
    )
    # ──────────────────────────────────────────────────────────────────────

    # Enable high-DPI scaling if available
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # ─── Initialize IC4 globally so MainWindow can enumerate devices ─────────
    ic4_initialized = False
    if ic4 is not None and config.CAMERA_BACKEND == "ic4":
        try:
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
            )
            ic4_initialized = True
            log.info("Global IC4 Library.init() succeeded.")
        except Exception as e:
            log.error(f"Could not initialize IC4 in main thread: {e}")
            # You might still allow the UI to start (with an empty device list),
            # or choose to exit right here with sys.exit(1).
    else:
        if ic4 is None:
            log.info("imagingcontrol4 not available; running without IC4 backend.")
        else:
            log.info(
                "Skipping IC4 initialization because backend '%s' is active.",
                config.CAMERA_BACKEND,
            )

    # Create the QApplication
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    if APP_SETTINGS_AVAILABLE and SETTING_RESULTS_DIR is not None:
        saved_dir = load_app_setting(SETTING_RESULTS_DIR, config.BURST_RESULTS_DIR)
        if saved_dir:
            config.set_results_dir(saved_dir)

    # Log what OpenGL/QSurfaceFormat we actually got
    actual_fmt = QSurfaceFormat.defaultFormat()
    profile_str = (
        "Core"
        if actual_fmt.profile() == QSurfaceFormat.CoreProfile
        else (
            "Compatibility"
            if actual_fmt.profile() == QSurfaceFormat.CompatibilityProfile
            else "NoProfile"
        )
    )
    log.info(
        f"Actual default QSurfaceFormat after QApplication init: "
        f"Version {actual_fmt.majorVersion()}.{actual_fmt.minorVersion()}, Profile: {profile_str}"
    )

    # ─── Load & Apply App Icon ─────────────────────────────────────────────
    base_dir = resource_path()
    icon_dir = os.path.join(base_dir, "ui", "icons")
    if not os.path.isdir(icon_dir):
        alt_icon_dir = os.path.join(
            os.path.dirname(base_dir), "buti_app", "ui", "icons"
        )
        if os.path.isdir(alt_icon_dir):
            icon_dir = alt_icon_dir
        else:
            log.warning(f"Icon directory not found in {icon_dir} or {alt_icon_dir}")

    ico_path = os.path.join(icon_dir, "BURST.ico")
    png_path = os.path.join(icon_dir, "BURST.png")
    app_icon = QIcon()
    if os.path.exists(ico_path):
        app_icon.addFile(ico_path)
    elif os.path.exists(png_path):
        app_icon.addFile(png_path)

    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    else:
        log.warning("No application icon file (BURST.ico or BURST.png) found.")

    # ─── Install a Custom Exception Hook for Unhandled Errors ─────────────
    def custom_exception_handler(exc_type, value, tb):
        err_msg = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNHANDLED PYTHON EXCEPTION:\n{err_msg}")

        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Critical Error",
            "An unexpected error occurred. The application may be unstable.\n"
            "Check the logs for details.",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(err_msg)
        dlg.exec_()

    sys.excepthook = custom_exception_handler

    # ─── Load Application QSS (if present) ────────────────────────────────
    style_path = os.path.join(base_dir, "ui", "style.qss")
    if os.path.exists(style_path):
        try:
            with open(style_path, "r") as f:
                app.setStyleSheet(f.read())
            log.info(f"Applied stylesheet from: {style_path}")
        except Exception as e:
            log.warning(
                f"Failed to load stylesheet {style_path}: {e}. Using default 'Fusion' style."
            )
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        log.info("No style.qss found. Using default 'Fusion' style.")
        app.setStyle(QStyleFactory.create("Fusion"))

    # ─── Import & Launch MainWindow ───────────────────────────────────────
    from main_window import MainWindow
    from ui.welcome_dialog import WelcomeDialog

    main_win = MainWindow()
    display_version = CONFIG_APP_VERSION or "Unknown"
    main_win.setWindowTitle(f"{APP_NAME} v{display_version}")
    main_win.show()

    welcome = WelcomeDialog(parent=main_win)
    if not getattr(welcome, "_skip", False):
        welcome.exec_()

    exit_code = app.exec_()
    log.info(f"Application event loop ended with exit code {exit_code}.")

    if ic4_initialized:
        try:
            ic4.Library.shutdown()
        except Exception:
            pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main_app_entry()
