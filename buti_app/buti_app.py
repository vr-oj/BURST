# File: buti_app/buti_app.py

import sys
import os
import re
import traceback
import logging
import platform
from logging.handlers import RotatingFileHandler
try:
    import imagingcontrol4 as ic4  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    ic4 = None

from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QUrl
from PyQt5.QtGui import (
    QIcon,
    QSurfaceFormat,
    QPalette,
    QColor,
    QDesktopServices,
)
import utils.config as config
from utils.config import APP_NAME, APP_VERSION as CONFIG_APP_VERSION
from utils.path_helpers import resource_path

import matplotlib

logging.getLogger("matplotlib").setLevel(logging.INFO)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)

log = logging.getLogger(__name__)


def configure_diagnostic_logging(log_path=None):
    """Start bounded application logging and return the active log path.

    Logging is configured only when the real application starts. Importing
    BURST modules for tests or utilities therefore does not create a log file.
    """
    log_path = log_path or config.DIAGNOSTIC_LOG_PATH
    console_handler = logging.StreamHandler(sys.stdout)
    handlers = [console_handler]
    active_log_path = None

    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handlers.insert(
            0,
            RotatingFileHandler(
                log_path,
                maxBytes=2 * 1024 * 1024,
                backupCount=1,
                encoding="utf-8",
            ),
        )
        active_log_path = log_path
    except OSError as exc:
        # A log-folder permission problem should not prevent BURST from
        # launching. The console still receives the diagnostic message.
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s",
            handlers=handlers,
            force=True,
        )
        log.exception("Could not create the diagnostic log at %s: %s", log_path, exc)
        return None

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s",
        handlers=handlers,
        force=True,
    )
    log.info(
        "BURST v%s started | Python %s | %s | frozen=%s",
        CONFIG_APP_VERSION or "Unknown",
        platform.python_version(),
        platform.platform(),
        bool(getattr(sys, "frozen", False)),
    )
    log.info("Diagnostic log: %s", active_log_path)
    return active_log_path


def flush_diagnostic_log():
    """Flush all logging handlers so a crash report is ready to send."""
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except (OSError, ValueError):
            pass


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
    active_log_path = configure_diagnostic_logging()

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
        flush_diagnostic_log()

        if active_log_path:
            log_instructions = (
                "A diagnostic log was saved here:\n"
                f"{active_log_path}\n\n"
                "Please send BURST-diagnostic.log when reporting this problem."
            )
        else:
            log_instructions = (
                "BURST could not write a diagnostic log. Copy the error details "
                "below when reporting this problem."
            )

        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Critical Error",
            "An unexpected error occurred. The application may be unstable.\n"
            f"\n{log_instructions}",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(err_msg)
        open_log_folder_button = None
        if active_log_path:
            open_log_folder_button = dlg.addButton(
                "Open Log Folder", QMessageBox.ActionRole
            )
        dlg.exec_()
        if dlg.clickedButton() is open_log_folder_button:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(active_log_path))
            )

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

    main_win.check_for_recoverable_recordings()

    # Match BRAID's silent startup behavior, after the welcome dialog is out
    # of the way so an available-update prompt cannot compete with it.
    main_win.start_update_check()

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
