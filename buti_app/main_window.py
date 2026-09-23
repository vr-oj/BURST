# buti_app/main_window.py

import os
import sys
import re
import logging
import csv
import json
import time
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QDockWidget,
    QTextEdit,
    QToolBar,
    QStatusBar,
    QAction,
    QActionGroup,
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QComboBox,
    QLabel,
    QPushButton,
    QMessageBox,
    QSizePolicy,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QSplitter,
)
from PyQt5.QtCore import (
    Qt,
    pyqtSlot,
    QTimer,
    QVariant,
    QSize,
    QThread,
    QMetaObject,
    QProcess,
)
from PyQt5.QtGui import QIcon, QKeySequence, QImage, QDesktopServices
from PyQt5.QtCore import QUrl
try:
    from PyQt5.QtMultimedia import QSoundEffect
except ImportError:  # pragma: no cover - platform packaging fallback
    QSoundEffect = None

import buti_app

from utils.app_settings import (
    save_app_setting,
    load_app_setting,
    SETTING_LAST_CAMERA_INDEX,
    SETTING_RESULTS_DIR,
    SETTING_COMPLETION_SOUND,
    SETTING_COMPLETION_SOUND_ID,
)
from utils.completion_sounds import (
    COMPLETION_SOUNDS,
    DEFAULT_COMPLETION_SOUND,
    get_completion_sound,
)
import utils.config as config
from utils.config import (
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    APP_NAME,
    APP_VERSION,
    set_results_dir,
    DEFAULT_VIDEO_EXTENSION,
    DEFAULT_VIDEO_CODEC,
    ABOUT_TEXT,
    RELEASES_URL,
    PLOT_DEFAULT_Y_MIN,
    PLOT_DEFAULT_Y_MAX,
    SERIAL_CMD_START,
    SERIAL_CMD_STOP,
)
from utils.path_helpers import get_next_run_folder, list_session_names, resource_path
from utils.braid_connector import braid_launch_command, find_braid_application
from utils.preflight import run_recording_preflight, PreflightCheck
from utils.camera_rate import CameraRateMonitor, check_camera_rate, RateCheck, RATE_GUIDANCE
from utils.buti_protocol import BoxObservation, PROTOCOL_NOTE, RATE_SETUP, SUPPORTED_COMMANDS
from ui.box_status_dialog import BoxStatusDialog
from utils.recording_files import rename_recording_pair, validate_path_component
from utils.recording_recovery import (
    find_recoverable_manifests,
    recover_partial_recording,
    update_manifest_file_names,
)
from utils.update_checker import UpdateChecker
from ui.canvas.qtcamera_widget import QtCameraWidget
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.control_panels.camera_info_panel import CameraInfoPanel
from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.plot_control_panel import PlotControlPanel
from ui.recording_completion_dialog import RecordingCompletionDialog
from ui.style_constants import PANEL_STYLESHEET
from ui.canvas.force_plot_widget import ForcePlotWidget

from threads.serial_thread import SerialThread
from cameras import CameraRegistry
from cameras.trigger import AUTO_TRIGGER
from recording_manager import RecordingManager
from utils.utils import list_serial_ports
from playback_window import PlaybackWindow

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # ─── State Variables ─────────────────────────────────────────────────────
        self._serial_thread = None
        self._serial_active = False
        self._recorder_thread = None
        self._recorder_worker = None
        self._current_run_folder = None
        self._last_recording_paths = {"tiff": None, "csv": None}
        self._serial_start_sent = False
        self._device_run_active = False
        self._buti_settings = {}
        self._buti_settings_received_at = None
        self._recording_state = "idle"
        self._current_session_name = None
        self._recording_had_output = False
        self._last_recording_summary = None
        self._last_camera_frame_monotonic = None
        self._camera_rate_monitor = CameraRateMonitor()
        self._box_observation = BoxObservation()
        self._recording_capture_mode = "box"
        self._hardware_trigger_source = AUTO_TRIGGER
        self._camera_armed = False
        self._timing_transition = ""
        self._preview_fps_at_recording = None
        self._timing_timer = QTimer(self)
        self._timing_timer.setSingleShot(True)
        self._timing_timer.timeout.connect(self._on_timing_timeout)
        self._completion_sound_enabled = bool(
            load_app_setting(SETTING_COMPLETION_SOUND, True)
        )
        self._completion_sound_id = get_completion_sound(
            load_app_setting(
                SETTING_COMPLETION_SOUND_ID,
                DEFAULT_COMPLETION_SOUND,
            )
        )["id"]
        self._completion_sound_effect = None
        self._completion_sound_actions = {}
        self.update_checker = None
        self._update_check_manual = False
        self._update_check_found = False
        self._update_check_failed = False
        self._closing = False
        # Camera orientation is deliberately scoped to this app run. A transform
        # chosen for one setup must not silently change the next live preview.
        self._mirror_horizontal = False
        self._mirror_vertical = False

        # Camera‐related
        self.device_combo = None
        self.resolution_combo = None
        self.btn_start_camera = None
        self.camera_widget = None
        self.camera_control_panel = None
        self.camera_info_panel = None
        self.camera_tabs = None
        self.camera_thread = None

        # Plot controls
        self.plot_control_panel = None
        self.workspace_splitter = None

        # Top control (BUTI Arduino Box status)
        self.top_ctrl = None


        # Plotting
        self.force_plot_widget = None

        self.camera_registry = CameraRegistry(config.CAMERA_BACKEND)
        self.camera_registry.set_micro_manager_profiles(load_app_setting("micro_manager_profiles", []))
        self._init_paths_and_icons()
        self._init_completion_sound()
        self._build_console_log_dock()
        self._build_central_widget_layout()
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        # Populate device list so user can select camera
        self._populate_device_list()
        self._set_initial_control_states()
        self.camera_info_panel.rate_help_button.clicked.connect(self._show_camera_rate_help)
        self.camera_info_panel.rate_help_button.setText("Recording help")
        self.camera_control_panel.camera_settings_changed.connect(self._camera_rate_monitor.reset)
        self._camera_rate_timer = QTimer(self)
        self._camera_rate_timer.setInterval(1000)
        self._camera_rate_timer.timeout.connect(self._update_camera_rate_status)
        self._camera_rate_timer.start()

        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION}")
        log.info("MainWindow initialized.")
        self.showMaximized()
        QTimer.singleShot(0, self._equalize_workspace_panels)
        QTimer.singleShot(250, self._equalize_workspace_panels)

    # ─── UI Builders ────────────────────────────────────────────────────────

    def _init_paths_and_icons(self):
        base = resource_path()
        icon_dir = os.path.join(base, "ui", "icons")
        if not os.path.isdir(icon_dir):
            alt_icon_dir = os.path.join(
                os.path.dirname(base), "buti_app", "ui", "icons"
            )
            if os.path.isdir(alt_icon_dir):
                icon_dir = alt_icon_dir
            else:
                another_alt_icon_dir = os.path.join(
                    os.path.dirname(base), "ui", "icons"
                )
                if os.path.isdir(another_alt_icon_dir):
                    icon_dir = another_alt_icon_dir
                else:
                    log.warning(
                        f"Icon directory not found. Looked in: {icon_dir}, {alt_icon_dir}, {another_alt_icon_dir}"
                    )

        def get_icon(name):
            path = os.path.join(icon_dir, name)
            return QIcon(path) if os.path.exists(path) else QIcon()

        self.icon_record_start = get_icon("record.svg")
        self.icon_record_stop = get_icon("stop.svg")
        self.icon_recording_active = get_icon("recording_active.svg")
        self.icon_connect = get_icon("plug.svg")
        self.icon_disconnect = get_icon("plug_disconnect.svg")
        self.icon_refresh = get_icon("sync.svg")
        self.icon_playback = get_icon("image.svg")

    def _init_completion_sound(self):
        """Preload the selected completion cue, retaining a system-beep fallback."""

        if QSoundEffect is None:
            return
        sound = get_completion_sound(self._completion_sound_id)
        sound_path = resource_path("ui", "sounds", sound["filename"])
        if not os.path.exists(sound_path):
            log.warning("Recording completion sound is missing: %s", sound_path)
            return
        try:
            effect = self._completion_sound_effect or QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(sound_path))
            effect.setVolume(sound["volume"])
            self._completion_sound_effect = effect
        except Exception:
            log.exception("Unable to initialize the recording completion sound")

    def _play_completion_sound(self, *, preview=False):
        if not preview and not self._completion_sound_enabled:
            return
        try:
            if self._completion_sound_effect is not None:
                if self._completion_sound_effect.status() != QSoundEffect.Error:
                    self._completion_sound_effect.play()
                    return
        except Exception:
            log.exception("Unable to play the recording completion sound")
        QApplication.beep()

    def _build_console_log_dock(self):
        self.dock_console = QDockWidget("Console Log", self)
        self.dock_console.setObjectName("ConsoleLogDock")
        self.dock_console.setAllowedAreas(
            Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
        )
        console_widget = QWidget()
        layout = QVBoxLayout(console_widget)
        self.console_out_textedit = QTextEdit(readOnly=True)
        self.console_out_textedit.setFontFamily("monospace")
        layout.addWidget(self.console_out_textedit)
        self.dock_console.setWidget(console_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)
        self.dock_console.setVisible(False)

    def _build_central_widget_layout(self):
        """
        Top: shallow, full-width BUTI status and command strip.
        Bottom: resizable Camera and Plot workspaces, each with local controls.
        """
        self.camera_widget = QtCameraWidget(self)

        central = QWidget()
        main_vlay = QVBoxLayout(central)
        main_vlay.setContentsMargins(4, 4, 4, 4)
        main_vlay.setSpacing(6)

        # ─── Global BUTI status strip ─────────────────────────────────────
        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.zero_requested.connect(self._on_zero_burst)
        self.top_ctrl.start_requested.connect(self._on_start_pump)
        self.top_ctrl.stop_requested.connect(self._on_stop_pump)
        self.top_ctrl.reset_requested.connect(self._on_reset_burst)
        self.top_ctrl.step_requested.connect(self._on_step)
        self.top_ctrl.record_requested.connect(self._toggle_recording)
        main_vlay.addWidget(self.top_ctrl, stretch=0)

        # ─── Camera workspace ─────────────────────────────────────────────
        self.workspace_splitter = QSplitter(Qt.Horizontal, central)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(6)

        camera_workspace = QWidget()
        camera_workspace.setObjectName("CameraWorkspace")
        camera_layout = QVBoxLayout(camera_workspace)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.setSpacing(6)

        self.camera_info_panel = CameraInfoPanel(self)
        self.device_combo = QComboBox(self)
        self.device_combo.addItem("Choose camera…", None)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)

        self.resolution_combo = QComboBox(self)
        self.resolution_combo.addItem("Choose resolution…", None)
        self.resolution_combo.currentIndexChanged.connect(
            self._on_camera_configuration_changed
        )
        self.resolution_combo.activated.connect(self._select_micro_manager_size)

        self.btn_start_camera = QPushButton("Start Camera", self)
        self.btn_start_camera.setProperty("cssClass", "primary")
        self.btn_start_camera.clicked.connect(self._on_start_stop_camera)

        self.camera_info_panel.mirror_horizontal_cb.setChecked(
            self._mirror_horizontal
        )
        self.camera_info_panel.mirror_vertical_cb.setChecked(
            self._mirror_vertical
        )
        self.camera_info_panel.mirror_horizontal_cb.toggled.connect(
            self._on_camera_transform_changed
        )
        self.camera_info_panel.mirror_vertical_cb.toggled.connect(
            self._on_camera_transform_changed
        )
        self.camera_info_panel.roi_button.clicked.connect(self._begin_live_roi)
        self.camera_info_panel.clear_roi_button.clicked.connect(
            self.camera_widget.clear_roi
        )
        self.camera_widget.roi_changed.connect(self._on_live_roi_changed)
        self.camera_widget.roi_edit_finished.connect(self._on_live_roi_finished)
        self.camera_widget.set_mirroring(
            self._mirror_horizontal, self._mirror_vertical
        )

        self.camera_control_panel = CameraControlPanel(parent=self, embedded=True)
        self.camera_control_panel.setEnabled(False)
        self.camera_info_panel.set_control_panel(self.camera_control_panel)

        self.camera_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        camera_layout.addWidget(self.camera_info_panel, stretch=0)
        camera_layout.addWidget(self.camera_widget, stretch=1)

        # ─── Plot workspace ───────────────────────────────────────────────
        plot_workspace = QWidget()
        plot_workspace.setObjectName("PlotWorkspace")
        plot_layout = QVBoxLayout(plot_workspace)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(6)

        self.plot_control_panel = PlotControlPanel(self)
        self.force_plot_widget = ForcePlotWidget(self)
        self.force_plot_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        plot_layout.addWidget(self.plot_control_panel, stretch=0)
        plot_layout.addWidget(self.force_plot_widget, stretch=1)

        self.workspace_splitter.addWidget(camera_workspace)
        self.workspace_splitter.addWidget(plot_workspace)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([1000, 1000])
        main_vlay.addWidget(self.workspace_splitter, stretch=1)

        # ─── Wire Up PlotControlPanel → ForcePlotWidget ────────────────
        if hasattr(self.force_plot_widget, "set_auto_scale_x"):
            self.plot_control_panel.autoscale_x_changed.connect(
                self.force_plot_widget.set_auto_scale_x
            )
        if hasattr(self.force_plot_widget, "set_auto_scale_y"):
            self.plot_control_panel.autoscale_y_changed.connect(
                self.force_plot_widget.set_auto_scale_y
            )
        if hasattr(self.force_plot_widget, "set_manual_x_limits"):
            self.plot_control_panel.x_axis_limits_changed.connect(
                self.force_plot_widget.set_manual_x_limits
            )
        if hasattr(self.force_plot_widget, "set_manual_y_limits"):
            self.plot_control_panel.y_axis_limits_changed.connect(
                self.force_plot_widget.set_manual_y_limits
            )
        if hasattr(self.force_plot_widget, "reset_zoom"):
            self.plot_control_panel.reset_zoom_requested.connect(
                lambda: self.force_plot_widget.reset_zoom(
                    self.plot_control_panel.is_autoscale_x(),
                    self.plot_control_panel.is_autoscale_y(),
                )
            )
        if hasattr(self.force_plot_widget, "export_as_image"):
            self.plot_control_panel.export_plot_image_requested.connect(
                self.force_plot_widget.export_as_image
            )
        if hasattr(self.force_plot_widget, "clear_plot"):
            self.plot_control_panel.clear_plot_requested.connect(
                self.force_plot_widget.clear_plot
            )
        self.setCentralWidget(central)

    def _equalize_workspace_panels(self):
        """Give the two local control cards equal dimensions after layout."""

        if not self.camera_info_panel or not self.plot_control_panel:
            return
        target_height = max(
            self.camera_info_panel.sizeHint().height(),
            self.plot_control_panel.sizeHint().height(),
        )
        self.camera_info_panel.setFixedHeight(target_height)
        self.plot_control_panel.setFixedHeight(target_height)

        available = max(
            2,
            self.workspace_splitter.width() - self.workspace_splitter.handleWidth(),
        )
        left_width = available // 2
        self.workspace_splitter.setSizes([left_width, available - left_width])

    # ─── Camera Device & Resolution Enumeration ─────────────────────────────
    @staticmethod
    def _fit_combo_popup(combo: QComboBox) -> None:
        """Keep toolbar fields compact while showing complete popup entries."""

        if combo.count() <= 0:
            return
        metrics = combo.fontMetrics()
        content_width = max(
            metrics.horizontalAdvance(combo.itemText(index))
            for index in range(combo.count())
        )
        popup_width = max(combo.minimumWidth(), min(content_width + 52, 620))
        combo.view().setMinimumWidth(popup_width)

    def _populate_device_list(self):
        if self.camera_thread is not None:
            self.statusBar().showMessage("Stop the camera before refreshing devices.", 3000)
            return
        previous = self.device_combo.currentData()
        self.device_combo.clear()
        self.device_combo.addItem("Choose camera…", None)
        selected = 0
        for device in self.camera_registry.discover_cameras():
            self.device_combo.addItem(device.display_name, device)
            if previous and (device.backend, device.id) == (previous.backend, previous.id):
                selected = self.device_combo.count() - 1
        if selected or self.device_combo.count() == 2:
            self.device_combo.setCurrentIndex(selected or 1)
        self._fit_combo_popup(self.device_combo)

    def _refresh_serial_port_list(self):
        ports = list_serial_ports()
        self.serial_port_combobox.clear()
        if ports:
            for p_dev, p_desc in ports:
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p_dev)} ({p_desc})", QVariant(p_dev)
                )
            self.serial_port_combobox.setEnabled(True)
        else:
            self.serial_port_combobox.addItem("No Serial Ports Found", QVariant())
            self.serial_port_combobox.setEnabled(False)

    @pyqtSlot()
    def _refresh_device_lists(self):
        """Re-enumerate cameras and serial ports."""
        self._populate_device_list()
        self._refresh_serial_port_list()
        self.statusBar().showMessage("Device lists refreshed", 3000)

    @pyqtSlot(int)
    def _on_device_selected(self, index):
        """Populate modes through the selected backend, with no native SDK objects."""
        if self.camera_widget is not None:
            self.camera_widget.clear_roi()
        device = self.device_combo.itemData(index)
        # Approximate pairing is an explicit choice for this camera/session only.
        self._hardware_trigger_source = AUTO_TRIGGER
        self.timing_action.setChecked(False)
        self.resolution_combo.clear()
        self.resolution_combo.setToolTip("")
        self.resolution_combo.addItem("Choose resolution…", None)
        if device:
            for mode in self.camera_registry.list_modes(device):
                self.resolution_combo.addItem(mode.display_name, mode.as_tuple())
            if self.resolution_combo.count() > 1:
                self.resolution_combo.setCurrentIndex(1)
        self._fit_combo_popup(self.resolution_combo)

    @pyqtSlot()
    def _on_camera_configuration_changed(self):
        if self.camera_widget is not None:
            self.camera_widget.clear_roi()

    @pyqtSlot()
    def _on_camera_transform_changed(self):
        self._mirror_horizontal = bool(
            self.camera_info_panel.mirror_horizontal_cb.isChecked()
        )
        self._mirror_vertical = bool(
            self.camera_info_panel.mirror_vertical_cb.isChecked()
        )
        self.camera_widget.set_mirroring(
            self._mirror_horizontal, self._mirror_vertical
        )

    @pyqtSlot()
    def _begin_live_roi(self):
        if not self.camera_widget.begin_roi_edit():
            self.statusBar().showMessage("Start the camera before drawing an ROI.", 3000)
            return
        self.statusBar().showMessage(
            "Drag over the full camera image to choose the recording ROI.", 5000
        )

    @pyqtSlot(object)
    def _on_live_roi_changed(self, roi):
        camera_active = self.camera_thread is not None and self.camera_thread.isRunning()
        self.camera_info_panel.set_roi_available(camera_active, roi is not None)

    @pyqtSlot(object)
    def _on_live_roi_finished(self, roi):
        source_size = self.camera_widget.source_size()
        if roi is None or source_size is None:
            return
        from utils.roi import normalized_roi_to_bounds

        width, height = source_size
        bounds = normalized_roi_to_bounds(roi, (height, width))
        if bounds:
            x0, y0, x1, y1 = bounds
            self.statusBar().showMessage(
                f"Recording ROI selected: {x1 - x0}×{y1 - y0} pixels.", 4000
            )

    @pyqtSlot()
    def _on_start_stop_camera(self):
        """
        Called when the user clicks “Start Camera” or “Stop Camera”.
        """
        if self.camera_thread is None:
            # ─── Start camera ─────────────────────────────────────────────────
            dev_info = self.device_combo.currentData()
            if dev_info is None:
                QMessageBox.warning(self, "Camera", "Please select a device first.")
                return

            resdata = self.resolution_combo.currentData()
            if not resdata:
                QMessageBox.warning(self, "Camera", "Please select a resolution first.")
                return

            w, h, pf_name = resdata
            self._last_camera_frame_monotonic = None
            self._camera_rate_monitor.reset()

            try:
                self.camera_thread = self.camera_registry.get_thread(dev_info, parent=self)
            except Exception as exc:
                self._on_camera_error(str(exc), "camera-open")
                return
            self._camera_armed = False
            # Preview always free-runs. Arm only at the recording boundary.
            self.camera_thread.hardware_trigger_source = ""
            if hasattr(self.camera_thread, "timing_ready"):
                self.camera_thread.timing_ready.connect(self._on_camera_timing_ready)
            self.camera_thread.set_resolution((w, h, pf_name))
            self.camera_thread.grabber_ready.connect(self._on_grabber_ready)
            self.camera_thread.frame_ready.connect(self.camera_widget._on_frame_ready)
            self.camera_thread.frame_ready.connect(self._update_camera_info)
            self.camera_thread.error.connect(self._on_camera_error)
            self.camera_thread.finished.connect(self._on_camera_finished)
            self.camera_control_panel.set_controller(None)
            self.camera_control_panel.setEnabled(False)
            self.device_combo.setEnabled(False)
            self.resolution_combo.setEnabled(False)

            # Show “Connecting…” in the Camera tab
            self.camera_info_panel.update_status("Connecting…", state="warning")
            self.camera_info_panel.reset_metrics()
            self.camera_info_panel.set_status_message("Connecting to camera…")

            # Actually start the thread
            self.camera_thread.start()
            self.btn_start_camera.setText("Stop Camera")
            self._refresh_recording_button_states()

        else:
            # ─── Stop camera ──────────────────────────────────────────────────
            if self._recording_state in {"preparing", "recording"}:
                self._request_recording_stop(
                    send_device_stop=True, reason="camera stopped"
                )
            self.camera_control_panel.set_controller(None)
            self.camera_thread.stop()
            self.btn_start_camera.setEnabled(False)
            self.btn_start_camera.setText("Stopping…")
            return

    @pyqtSlot()
    def _on_camera_finished(self):
        thread = self.sender()
        if thread is not self.camera_thread:
            return
        if self._recording_state in {"preparing", "recording"}:
            self._request_recording_stop(send_device_stop=True, reason="camera ended")
        self.camera_control_panel.set_controller(None)
        self.camera_control_panel.setEnabled(False)
        self.camera_thread = None
        self._camera_armed = False
        self._timing_transition = ""
        self._timing_timer.stop()
        thread.deleteLater()
        self._last_camera_frame_monotonic = None
        can_select = self._recording_state == "idle"
        self.btn_start_camera.setEnabled(can_select)
        self.btn_start_camera.setText("Start Camera")
        self.device_combo.setEnabled(can_select)
        self.resolution_combo.setEnabled(can_select)
        if self.camera_info_panel.status_text() != "Error":
            self.camera_info_panel.update_status("Disconnected")
            self.camera_info_panel.set_status_message("Camera idle.")
        self.camera_info_panel.reset_metrics()
        self.camera_widget.clear_image()
        self.camera_info_panel.set_roi_available(False, self.camera_widget.normalized_roi() is not None)
        self._refresh_recording_button_states()

    @pyqtSlot()
    def _on_grabber_ready(self):
        if (self.camera_thread is None or self.sender() is not self.camera_thread
                or not self.camera_thread.isRunning()):
            return
        self.camera_control_panel.set_controller(self.camera_thread.controller)
        self._camera_armed = bool(getattr(self.camera_thread, "trigger_configuration", {}))
        self.camera_control_panel.setEnabled(not self._camera_armed)
        diagnostics = self.camera_thread.controller.diagnostics()
        self._update_micro_manager_resolution(diagnostics.get("image_width"), diagnostics.get("image_height"))

        self.camera_info_panel.update_status("Connected", state="connected")
        self.camera_info_panel.set_status_message("Armed: waiting for Arduino pulses" if self._camera_armed else "Streaming")
        self.camera_info_panel.set_roi_available(
            True, self.camera_widget.normalized_roi() is not None
        )
        self._refresh_recording_button_states()

    def _update_micro_manager_resolution(self, width, height):
        device = self.device_combo.currentData()
        if (device is not None and device.backend == "micromanager"
                and isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0):
            controller = self.camera_thread.controller if self.camera_thread else None
            controls = controller.capabilities() if controller else {}
            binning = controls.get("mm:Binning")
            roi = controls.get("mmcore:Sensor ROI (x,y,width,height)")
            options = [(f"{width}×{height} (Current)", (width, height, "Configuration"))]
            if roi and roi.writable:
                options += [("Full sensor", {"roi": "0,0,0,0"}), ("Custom sensor region…", {"roi": "custom"})]
            if binning and binning.writable:
                options += [(f"Binning {value}", {"binning": value}) for value in binning.choices]
            if options != getattr(self, "_mm_size_options", None) or self.resolution_combo.itemData(0) != options[0][1]:
                self._mm_size_options = options
                blocked = self.resolution_combo.blockSignals(True)
                self.resolution_combo.clear()
                for label, value in options:
                    self.resolution_combo.addItem(label, value)
                self.resolution_combo.blockSignals(blocked)
            self.resolution_combo.setEnabled(self._recording_state == "idle" and not self._camera_armed
                                             and not self._timing_transition and controller is not None)
            self.resolution_combo.setToolTip("Camera acquisition size. Binning and sensor regions change images received from the camera; recording crop only changes saved images.")

    def _select_micro_manager_size(self, index):
        action = self.resolution_combo.itemData(index)
        if not isinstance(action, dict):
            return
        self.resolution_combo.setCurrentIndex(0)
        if (self.camera_thread is None or self._recording_state != "idle"
                or self._camera_armed or self._timing_transition):
            return
        controller = self.camera_thread.controller
        if "binning" in action:
            controller.set_value("mm:Binning", action["binning"])
        else:
            value = action["roi"]
            if value == "custom":
                from ui.micro_manager_sensor import SensorROIDialog
                control = controller.capabilities().get("mmcore:Sensor ROI (x,y,width,height)")
                if control is None:
                    return
                dialog = SensorROIDialog(tuple(int(v) for v in str(control.value).split(",")), self)
                if dialog.exec_() != QDialog.Accepted:
                    return
                value = dialog.value()
            controller.set_value("mmcore:Sensor ROI (x,y,width,height)", value)
        self._camera_rate_monitor.reset()

    @pyqtSlot(QImage, object)
    def _update_camera_info(self, image: QImage, raw):
        """
        (Optional) Keep updating frame count & resolution in the “Camera” tab
        every time a new frame arrives.  If you want to hook this up, simply:
            self.camera_thread.frame_ready.connect(self._update_camera_info)
        """
        self._last_camera_frame_monotonic = time.monotonic()
        self._camera_rate_monitor.observe(self._last_camera_frame_monotonic)
        self.camera_info_panel.increment_frame_count()

        width = image.width()
        height = image.height()
        self.camera_info_panel.set_resolution(f"{width}×{height}")
        self._update_micro_manager_resolution(width, height)

        if self.camera_info_panel.status_text() != "Connected":
            self.camera_info_panel.update_status("Connected", state="connected")
            self.camera_info_panel.set_status_message("Armed: waiting for Arduino pulses" if self._camera_armed else "Streaming")
            self.camera_info_panel.set_roi_available(
                self._recording_state == "idle",
                self.camera_widget.normalized_roi() is not None,
            )
            self._refresh_recording_button_states()

    def _setup_micro_manager(self):
        if self._recording_state != "idle" or self.camera_thread is not None:
            QMessageBox.information(self, "Stop Camera First", "Stop recording and stop the camera before changing Micro-Manager configurations.")
            return
        from ui.micro_manager_setup import MicroManagerSetupDialog
        from cameras.micro_manager_backend import PROFILE_SETTING
        backend = self.camera_registry.backends.get("micromanager")
        profiles = load_app_setting(PROFILE_SETTING, [])
        dialog = MicroManagerSetupDialog(backend.sdk if backend else None,
            profiles if isinstance(profiles, list) else [], self,
            self.camera_registry.unavailable.get("micromanager", ""))
        if dialog.exec_() == QDialog.Accepted:
            if save_app_setting(PROFILE_SETTING, dialog.profiles) is False:
                QMessageBox.warning(self, "Settings Could Not Be Saved", "BURST could not save the camera configuration locations. Check access to your user settings folder.")
                return
            self.camera_registry.set_micro_manager_profiles(dialog.profiles)
            self._populate_device_list()
            if dialog.profiles:
                for i in range(self.device_combo.count()):
                    device = self.device_combo.itemData(i)
                    if device and device.backend == "micromanager" and device.native_info == dialog.profiles[-1]:
                        self.device_combo.setCurrentIndex(i)
                        break

    def _camera_rate_check(self):
        if self._camera_armed:
            return RateCheck(True, "Camera armed for Arduino triggers.")
        if self._hardware_trigger_source:
            return RateCheck(True, "Preview ready. Camera triggering will be checked before recording.")
        measured = self._camera_rate_monitor.fps(time.monotonic())
        if measured is None:
            return check_camera_rate(None)
        target = self._box_observation.image_hz if self._device_run_active else None
        if target:
            return check_camera_rate(measured, target=target)
        return RateCheck(True, f"Receiving {measured:.2f} FPS.")

    def _update_camera_rate_status(self):
        if self.camera_thread is None or not self.camera_thread.isRunning():
            self._camera_rate_monitor.reset()
            self.camera_info_panel.rate_status.setText("Start the camera to preview and adjust the image.")
            self.camera_info_panel.rate_status.setStyleSheet("")
            return
        measured = self._camera_rate_monitor.fps(time.monotonic())
        self.camera_info_panel.set_fps(measured)
        check = self._camera_rate_check()
        if self._timing_transition:
            detail = "Preparing camera for recording…" if self._timing_transition == "arming" else "Returning to preview…"
        elif self._camera_armed:
            detail = "Arduino-triggered recording" if self._recording_state == "recording" else "Camera ready for Arduino triggers"
        elif self._hardware_trigger_source:
            detail = "Preview · Use ZERO on the Arduino box before recording."
        else:
            detail = "Approximate software pairing · " + check.detail
        self.camera_info_panel.rate_status.setText(detail)
        self.camera_info_panel.rate_status.setToolTip(
            "Arduino-triggered recording requires the trigger cable and a supported camera input. "
            "BURST checks settings and image/data association; physical exposure-to-force timing requires setup validation.")
        self.camera_info_panel.rate_status.setStyleSheet("" if check.passed else "color: #f3c969;")

    def _show_camera_rate_help(self, detail=None):
        if not isinstance(detail, str):
            detail = self._camera_rate_check().detail
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Camera Rate and Recording")
        dialog.setIcon(QMessageBox.Information)
        dialog.setText(detail)
        dialog.setInformativeText(RATE_GUIDANCE + "\n\n" + RATE_SETUP)
        controller = getattr(self.camera_thread, "controller", None)
        diagnostics = controller.diagnostics() if controller else {}
        dialog.setDetailedText("Camera diagnostics:\n" + json.dumps(diagnostics, indent=2))
        retry = None
        if self._recording_state == "idle" and not self._device_run_active and not self._timing_transition:
            fps = controller.capabilities().get("fps") if controller else None
            if fps and fps.writable:
                retry = dialog.addButton("Request 10 FPS preview", QMessageBox.ActionRole)
        dialog.addButton(QMessageBox.Close)
        dialog.exec_()
        if retry is not None and dialog.clickedButton() is retry:
            controller.set_value("fps", float(DEFAULT_FPS))
            self._camera_rate_monitor.reset()

    def _configure_timing(self, approximate):
        if self._recording_state != "idle" or self._device_run_active or self._timing_transition:
            self.timing_action.setChecked(not bool(self._hardware_trigger_source))
            return
        if approximate:
            answer = QMessageBox.warning(self, "Approximate recording",
                "Images will be paired with serial rows by arrival order. The camera will not follow "
                "the Arduino trigger cable, so exposure timing can drift.\n\n"
                "Use this only when approximate video timing is acceptable. Enable for this camera?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                self.timing_action.setChecked(False)
                return
        self._hardware_trigger_source = "" if approximate else AUTO_TRIGGER
        self.timing_action.setChecked(approximate)
        self._update_camera_rate_status()

    def _show_box_settings(self):
        BoxStatusDialog(self).exec_()

    def _set_capture_mode(self, mode):
        if self._recording_state != "idle" or self._device_run_active or self._timing_transition:
            self.statusBar().showMessage("Stop the run before changing BURST recording mode.", 4000)
            self.capture_mode_actions[self._recording_capture_mode].setChecked(True)
            return
        self._recording_capture_mode = mode
        self._refresh_recording_button_states()

    @pyqtSlot(str, str)
    def _on_camera_error(self, msg: str, code: str):
        """
        Show camera errors in a dialog, then reset UI to “off” state.
        """
        log.error(f"Camera error occurred ({code}): {msg}")
        self._camera_armed = False
        # If the thread is still running, stop it
        if self.camera_thread and self.camera_thread.isRunning():
            try:
                self.camera_thread.stop()
            except Exception:
                pass

        self.camera_control_panel.set_controller(None)
        self.camera_control_panel.setEnabled(False)
        self.camera_info_panel.update_status("Error", state="error")
        self.camera_info_panel.reset_metrics()
        self.camera_info_panel.set_status_message("Camera error.")
        self.camera_widget.clear_image()
        self._last_camera_frame_monotonic = None
        self.btn_start_camera.setText("Start Camera")
        self.camera_info_panel.set_roi_available(
            False, self.camera_widget.normalized_roi() is not None
        )
        if self._recording_state in {"preparing", "recording"} and self._recording_capture_mode != "force_only":
            self._request_recording_stop(send_device_stop=True, reason="camera error")
        self._refresh_recording_button_states()

        hint = "Please check the camera connection or restart the device."
        self._show_error_dialog(
            "Camera Error", f"{msg}\n\n{hint}", details=f"Code: {code}"
        )

    def _build_menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        exp_data_act = QAction(
            "Export Plot &Data (CSV)…", self, triggered=self._export_plot_data_as_csv
        )
        fm.addAction(exp_data_act)
        exp_img_act = QAction("Export Plot &Image…", self)
        exp_img_act.triggered.connect(self.force_plot_widget.export_as_image)
        fm.addAction(exp_img_act)
        playback_act = QAction(
            "Open &Playback Window…", self, triggered=lambda: self.open_playback_window(True)
        )
        fm.addAction(playback_act)
        choose_dir_act = QAction(
            "Set &Results Folder…", self, triggered=self._choose_results_dir
        )
        fm.addAction(choose_dir_act)
        fm.addSeparator()
        exit_act = QAction(
            "&Exit", self, shortcut=QKeySequence.Quit, triggered=self.close
        )
        fm.addAction(exit_act)

        am = mb.addMenu("&Acquisition")
        advanced = am.addMenu("Advanced")
        self.timing_action = QAction("Allow approximate software pairing", self, checkable=True)
        self.timing_action.triggered.connect(self._configure_timing)
        advanced.addAction(self.timing_action)
        advanced.addAction("Arduino box settings and status…", self._show_box_settings)
        capture_menu = advanced.addMenu("BURST recording mode")
        self.capture_mode_group = QActionGroup(self)
        self.capture_mode_group.setExclusive(True)
        self.capture_mode_actions = {}
        for mode, label in (("box", "Follow Arduino Capture setting"), ("force_only", "Force only (save no images in BURST)")):
            action = QAction(label, self, checkable=True)
            action.setChecked(mode == self._recording_capture_mode)
            action.triggered.connect(lambda checked, m=mode: self._set_capture_mode(m))
            self.capture_mode_group.addAction(action)
            capture_menu.addAction(action)
            self.capture_mode_actions[mode] = action
        self.micro_manager_setup_action = QAction("Micro-Manager Camera Setup…", self,
                                                triggered=self._setup_micro_manager)
        advanced.addAction(self.micro_manager_setup_action)
        self.recording_action = QAction(
            self.icon_record_start,
            "Start &Recording",
            self,
            triggered=self._toggle_recording,
            enabled=False,
        )
        self.recording_action.setShortcut(Qt.CTRL | Qt.Key_R)
        am.addAction(self.recording_action)
        self.change_session_action = QAction(
            "Change Recording &Session…",
            self,
            triggered=self._change_recording_session,
        )
        am.addAction(self.change_session_action)
        am.addSeparator()
        self.completion_sound_action = QAction(
            "Play Recording Completion &Sound", self, checkable=True
        )
        self.completion_sound_action.setChecked(self._completion_sound_enabled)
        self.completion_sound_action.toggled.connect(
            self._set_completion_sound_enabled
        )
        am.addAction(self.completion_sound_action)

        self.completion_sound_menu = am.addMenu("Completion Sound")
        self.completion_sound_group = QActionGroup(self)
        self.completion_sound_group.setExclusive(True)
        for sound in COMPLETION_SOUNDS:
            action = QAction(sound["label"], self, checkable=True)
            action.setChecked(sound["id"] == self._completion_sound_id)
            action.triggered.connect(
                lambda _checked=False, sound_id=sound["id"]: self._set_completion_sound_id(
                    sound_id
                )
            )
            self.completion_sound_group.addAction(action)
            self.completion_sound_menu.addAction(action)
            self._completion_sound_actions[sound["id"]] = action
        self.completion_sound_menu.addSeparator()
        preview_sound_action = QAction("Preview Selected Sound", self)
        preview_sound_action.triggered.connect(
            lambda _checked=False: self._play_completion_sound(preview=True)
        )
        self.completion_sound_menu.addAction(preview_sound_action)

        vm = mb.addMenu("&View")
        if hasattr(self, "dock_console") and self.dock_console:
            vm.addAction(self.dock_console.toggleViewAction())

        pm = mb.addMenu("&Plot")
        clear_plot_act = QAction(
            "&Clear Plot Data", self, triggered=self._clear_force_plot
        )
        pm.addAction(clear_plot_act)

        def trigger_reset_zoom():
            if hasattr(self.force_plot_widget, "reset_zoom"):
                self.force_plot_widget.reset_zoom(
                    self.plot_control_panel.is_autoscale_x(),
                    self.plot_control_panel.is_autoscale_y(),
                )
            else:
                log.warning("reset_zoom() not found on ForcePlotWidget")

        reset_zoom_act = QAction("&Reset Plot Zoom", self, triggered=trigger_reset_zoom)
        pm.addAction(reset_zoom_act)

        hm = mb.addMenu("&Help")
        welcome_act = QAction("&Show Welcome", self, triggered=self._show_welcome_dialog)
        hm.addAction(welcome_act)
        readme_act = QAction("&Open User Guide", self, triggered=self._open_readme)
        hm.addAction(readme_act)
        diagnostic_log_act = QAction(
            "Open &Diagnostic Log Folder",
            self,
            triggered=self._open_diagnostic_log_folder,
        )
        hm.addAction(diagnostic_log_act)
        update_act = QAction(
            "Check for &Updates…", self, triggered=lambda: self.start_update_check(True)
        )
        hm.addAction(update_act)
        hm.addSeparator()
        about_act = QAction(
            f"&About {APP_NAME}", self, triggered=self._show_about_dialog
        )
        hm.addAction(about_act)
        hm.addAction("About &Qt", QApplication.instance().aboutQt)

    def _build_main_toolbar(self):
        tb = QToolBar("Main Controls")
        tb.setObjectName("MainControlsToolbar")
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setStyleSheet(PANEL_STYLESHEET)
        self.addToolBar(Qt.TopToolBarArea, tb)

        # Refresh device lists
        self.refresh_action = QAction(
            self.icon_refresh,
            "&Refresh Devices",
            self,
            triggered=self._refresh_device_lists,
        )
        tb.addAction(self.refresh_action)

        # Serial port connect/disconnect
        self.connect_serial_action = QAction(
            self.icon_connect,
            "&Connect BUTI Arduino Box",
            self,
            triggered=self._toggle_serial_connection,
        )
        tb.addAction(self.connect_serial_action)

        self.serial_port_combobox = QComboBox()
        self.serial_port_combobox.setToolTip("Select Serial Port")
        self.serial_port_combobox.setMinimumWidth(200)
        self._refresh_serial_port_list()
        tb.addWidget(self.serial_port_combobox)
        tb.addSeparator()

        camera_group = QWidget(self)
        camera_group_layout = QHBoxLayout(camera_group)
        camera_group_layout.setContentsMargins(6, 0, 4, 0)
        camera_group_layout.setSpacing(6)

        camera_label = QLabel("Camera Device")
        camera_label.setProperty("cssClass", "panelTitle")
        camera_group_layout.addWidget(camera_label)
        self.device_combo.setMinimumWidth(250)
        self.device_combo.setMaximumWidth(370)
        self.device_combo.setToolTip("Select the camera device")
        camera_group_layout.addWidget(self.device_combo)

        resolution_label = QLabel("Resolution")
        resolution_label.setProperty("cssClass", "detailLabel")
        camera_group_layout.addWidget(resolution_label)
        self.resolution_combo.setMinimumWidth(205)
        self.resolution_combo.setMaximumWidth(270)
        self.resolution_combo.setToolTip("Select the camera resolution")
        camera_group_layout.addWidget(self.resolution_combo)
        self.btn_start_camera.setMinimumWidth(112)
        self.btn_start_camera.setMinimumHeight(30)
        camera_group_layout.addWidget(self.btn_start_camera)
        tb.addWidget(camera_group)
        tb.addSeparator()

        self.playback_action = QAction(
            self.icon_playback,
            "Playback Last Recording",
            self,
            triggered=self.open_playback_window,
            enabled=False,
        )
        tb.addAction(self.playback_action)

    def _build_status_bar(self):
        sb = self.statusBar()
        self.serial_status_label = QLabel("Serial: Disconnected")
        self.recording_status_label = QLabel("Not Recording")
        self.recording_session_label = QLabel("Recording Session: Not Selected")
        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.serial_status_label)
        sb.addPermanentWidget(self.recording_status_label)
        sb.addPermanentWidget(self.recording_session_label)
        sb.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self)
        self._app_session_timer.setInterval(1000)
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    @pyqtSlot()
    def _update_app_session_time(self):
        """
        Increment the session timer (in seconds) and update the status‐bar label.
        """
        self._app_session_seconds += 1
        hours, rem = divmod(self._app_session_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        self.app_session_time_label.setText(
            f"Session: {hours:02d}:{minutes:02d}:{seconds:02d}"
        )

    @pyqtSlot()
    def _clear_force_plot(self):
        if self.force_plot_widget and hasattr(
            self.force_plot_widget, "clear_plot"
        ):
            self.force_plot_widget.clear_plot()
            self.statusBar().showMessage("Force plot data cleared.", 3000)

    def _send_serial_command(self, command: str) -> bool:
        """Safely issue a single-character command to the serial thread."""

        if command not in SUPPORTED_COMMANDS:
            return False
        if not self._serial_thread or not self._serial_thread.isRunning():
            log.warning(
                "Attempted to send serial command '%s' but no serial connection is active.",
                command,
            )
            return False

        try:
            return bool(self._serial_thread.send_command(command))
        except Exception:
            log.exception("Failed to send serial command '%s'", command)
        return False

    @pyqtSlot()
    def _on_zero_burst(self):
        QMessageBox.information(self, "Use the box controls", "Use Home on the Arduino box. The published firmware has no remote Home command.")

    @pyqtSlot()
    def _on_start_pump(self):
        """Send the firmware start command without recording."""
        if self._recording_state != "idle" or self._device_run_active or self._timing_transition:
            self.statusBar().showMessage("The BUTI device is already running.", 3000)
            return
        if self._send_serial_command(SERIAL_CMD_START):
            self.statusBar().showMessage(
                "Run Device command sent; no recording files will be saved.", 4000
            )
            self._serial_start_sent = True
            self._device_run_active = True
            self.top_ctrl.set_run_state(True, connected=True)
            self._refresh_recording_button_states()
        else:
            self.statusBar().showMessage(
                "BUTI Arduino Box not connected; cannot send start command.", 3000
            )

    @pyqtSlot()
    def _on_stop_pump(self):
        """Send the firmware stop command."""
        if self._send_serial_command(SERIAL_CMD_STOP):
            self.statusBar().showMessage("Stop command sent to the BUTI Arduino Box.", 3000)
            self._device_run_active = False
            self.top_ctrl.set_run_state(False, connected=True)
        else:
            self.statusBar().showMessage(
                "BUTI Arduino Box not connected; cannot send stop command.", 3000
            )
        self._serial_start_sent = False
        if self._recording_state in {"preparing", "recording"}:
            self._request_recording_stop(
                send_device_stop=False, reason="Stop Device command"
            )

    @pyqtSlot()
    def _on_reset_burst(self):
        self._show_box_settings()

    @pyqtSlot()
    def _on_step(self):
        QMessageBox.information(self, "Step unavailable", "Remote Step is disabled pending corrections to timestamps and trigger counts in the Arduino firmware.")

    def _set_initial_control_states(self):
        if hasattr(self, "camera_control_panel"):
            self.camera_control_panel.setEnabled(False)
        if hasattr(self, "plot_control_panel"):
            self.plot_control_panel.setEnabled(True)
        self._refresh_recording_button_states()

    # ─── Menu Actions & Dialog Slots ──────────────────────────────────────────
    def _export_plot_data_as_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plot Data as CSV",
            config.BURST_RESULTS_DIR,
            "CSV Files (*.csv)",
        )
        if path:
            try:
                data = self.force_plot_widget.get_plot_data()  # assume method exists
                with open(path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Time (s)", "Force"])
                    for t, force in zip(data["time"], data["force"]):
                        writer.writerow([t, force])
                self.statusBar().showMessage(f"Plot data exported to {path}", 3000)
            except Exception as e:
                log.error(f"Error exporting CSV: {e}")
                QMessageBox.critical(
                    self, "Export Error", f"Failed to export CSV:\n{e}"
                )

    def _choose_results_dir(self):
        new_dir = QFileDialog.getExistingDirectory(
            self, "Select Results Folder", config.BURST_RESULTS_DIR
        )
        if new_dir:
            results_dir = os.path.join(new_dir, "BURST Results")
            set_results_dir(results_dir)
            save_app_setting(SETTING_RESULTS_DIR, results_dir)
            self._current_session_name = None
            if hasattr(self, "recording_session_label"):
                self.recording_session_label.setText(
                    "Recording Session: Not Selected"
                )
            self.statusBar().showMessage(f"Results folder set to {results_dir}", 5000)

    @pyqtSlot(bool)
    def _set_completion_sound_enabled(self, enabled: bool):
        self._completion_sound_enabled = bool(enabled)
        save_app_setting(SETTING_COMPLETION_SOUND, self._completion_sound_enabled)

    def _set_completion_sound_id(self, sound_id: str):
        sound = get_completion_sound(sound_id)
        self._completion_sound_id = sound["id"]
        save_app_setting(SETTING_COMPLETION_SOUND_ID, self._completion_sound_id)
        self._init_completion_sound()
        action = self._completion_sound_actions.get(self._completion_sound_id)
        if action is not None:
            action.setChecked(True)
        self._play_completion_sound(preview=True)

    @pyqtSlot()
    def _change_recording_session(self):
        if self._recording_state != "idle":
            return
        try:
            existing = list_session_names()
        except OSError as exc:
            self._show_error_dialog(
                "Recording Session Error",
                f"Unable to read the results folder:\n{exc}",
            )
            return
        default = self._current_session_name or (existing[0] if existing else "Session 1")
        choices = list(existing)
        if default not in choices:
            choices.insert(0, default)
        selected, accepted = QInputDialog.getItem(
            self,
            "Recording Session",
            "Select an existing session or type a new session name:",
            choices,
            max(0, choices.index(default)),
            True,
        )
        if not accepted:
            return
        try:
            self._current_session_name = validate_path_component(
                selected, label="Session name"
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Session Name", str(exc))
            return self._change_recording_session()
        self.statusBar().showMessage(
            f"Recording session: {self._current_session_name}", 5000
        )
        self.recording_session_label.setText(
            f"Recording Session: {self._current_session_name}"
        )
        self._refresh_recording_button_states()

    def _show_error_dialog(self, title: str, message: str, details: str = None):
        """Display a critical error dialog with optional details."""
        dlg = QMessageBox(
            QMessageBox.Critical,
            title,
            message,
            QMessageBox.Ok,
            self,
        )
        if details:
            dlg.setDetailedText(details)
        dlg.exec_()

    def _show_about_dialog(self):
        QMessageBox.information(self, f"About {APP_NAME}", ABOUT_TEXT)

    def start_update_check(self, manual: bool = False) -> None:
        """Check GitHub Releases without blocking the camera or serial UI."""

        checker = self.update_checker
        if checker is not None:
            try:
                if checker.isRunning():
                    self._update_check_manual = self._update_check_manual or manual
                    if manual:
                        self.statusBar().showMessage(
                            "An update check is already running…", 3000
                        )
                    return
            except RuntimeError:
                self.update_checker = None

        self._update_check_manual = bool(manual)
        self._update_check_found = False
        self._update_check_failed = False
        checker = UpdateChecker(APP_VERSION, RELEASES_URL, parent=self)
        checker.update_available.connect(self._on_update_available)
        checker.check_failed.connect(self._on_update_check_failed)
        checker.finished.connect(
            lambda current=checker: self._on_update_check_finished(current)
        )
        self.update_checker = checker
        if manual:
            self.statusBar().showMessage("Checking for BURST updates…")
        checker.start()

    @pyqtSlot(str, str)
    def _on_update_available(self, new_tag: str, release_url: str) -> None:
        if self._closing:
            return
        self._update_check_found = True
        log.info("BURST update available: %s", new_tag)

        display_tag = new_tag if new_tag.lower().startswith("v") else f"v{new_tag}"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Information)
        dialog.setWindowTitle("BURST Update Available")
        dialog.setTextFormat(Qt.RichText)
        dialog.setText(
            f"A new version of {APP_NAME} is available.<br><br>"
            f"Current version: <b>v{APP_VERSION}</b><br>"
            f"New version: <b>{display_tag}</b>"
        )
        dialog.setInformativeText(
            "Open the official GitHub release page to download the installer?"
        )
        open_button = dialog.addButton(
            "Open Release Page", QMessageBox.AcceptRole
        )
        dialog.addButton("Later", QMessageBox.RejectRole)
        dialog.exec_()
        if dialog.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(release_url or RELEASES_URL))

    @pyqtSlot(str)
    def _on_update_check_failed(self, message: str) -> None:
        self._update_check_failed = True
        if self._closing or not self._update_check_manual:
            return
        QMessageBox.warning(
            self,
            "Update Check Failed",
            "BURST could not reach GitHub Releases. Check the internet "
            "connection and try again.",
        )
        log.info("Manual update check failed: %s", message)

    def _on_update_check_finished(self, checker: UpdateChecker) -> None:
        if checker is not self.update_checker:
            checker.deleteLater()
            return
        if (
            self._update_check_manual
            and not self._update_check_found
            and not self._update_check_failed
            and not self._closing
        ):
            QMessageBox.information(
                self,
                "BURST Is Up to Date",
                f"BURST v{APP_VERSION} is the latest available version.",
            )
        self.statusBar().clearMessage()
        self.update_checker = None
        checker.deleteLater()

    def _show_welcome_dialog(self):
        from ui.welcome_dialog import WelcomeDialog
        dlg = WelcomeDialog(parent=self, force_show=True)
        dlg.exec_()

    def _open_readme(self):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "README.md"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_diagnostic_log_folder(self):
        try:
            os.makedirs(config.DIAGNOSTIC_LOG_DIR, exist_ok=True)
        except OSError as exc:
            log.error("Could not create diagnostic log folder: %s", exc)
            self._show_error_dialog(
                "Diagnostic Log Unavailable",
                "BURST could not open its diagnostic log folder.",
                details=str(exc),
            )
            return

        if not QDesktopServices.openUrl(
            QUrl.fromLocalFile(config.DIAGNOSTIC_LOG_DIR)
        ):
            log.error(
                "Failed to open diagnostic log folder %s",
                config.DIAGNOSTIC_LOG_DIR,
            )
            self._show_error_dialog(
                "Diagnostic Log Unavailable",
                "BURST could not open its diagnostic log folder.",
                details=config.DIAGNOSTIC_LOG_DIR,
            )

    # ─── Toggle Serial Connection ────────────────────────────────────────────
    def _toggle_serial_connection(self):
        """
        Toggle between Connect/Disconnect purely based on whether self._serial_thread
        is running.  No extra flags needed.

        - If _serial_thread is None or not running → start a new SerialThread,
          immediately set the QAction to “Disconnect BUTI Arduino Box,” and disable the combo.
        - Otherwise (thread is running) → stop it, set _serial_thread = None,
          immediately flip QAction back to “Connect BUTI Arduino Box,” and re‐enable the combo.
        """
        # (1) If there is no running thread, go into “CONNECT” branch
        if self._serial_thread is None or not self._serial_thread.isRunning():
            # --- User clicked “Connect BUTI Arduino Box” ---
            data = self.serial_port_combobox.currentData()
            port = data.value() if isinstance(data, QVariant) else data

            if port is None:
                QMessageBox.warning(self, "Serial Connection", "Please select a port.")
                return

            self._serial_start_sent = False
            self._box_observation.reset()
            self._buti_settings = {}
            self._buti_settings_received_at = None
            log.info(f"Starting SerialThread on port: {port}")
            try:
                # If there is any leftover object, force‐stop and delete it
                if self._serial_thread:
                    if self._serial_thread.isRunning():
                        self._serial_thread.stop()
                        if not self._serial_thread.wait(1000):
                            self._serial_thread.terminate()
                            self._serial_thread.wait(500)
                    self._serial_thread.deleteLater()
                    self._serial_thread = None

                # Create and start the new thread
                self._serial_thread = SerialThread(port=port, parent=self)
                self._serial_thread.stream_started.connect(
                    self._handle_serial_stream_started
                )
                self._serial_thread.stream_stopped.connect(
                    self._handle_serial_stream_stopped
                )
                self._serial_thread.data_ready.connect(self._handle_new_serial_data)
                self._serial_thread.settings_received.connect(
                    self._handle_buti_settings_received
                )
                self._serial_thread.error_occurred.connect(self._handle_serial_error)
                self._serial_thread.status_changed.connect(
                    self._handle_serial_status_change
                )
                self._serial_thread.finished.connect(
                    self._handle_serial_thread_finished
                )
                self._serial_thread.start()

                # Immediately flip the QAction to “Disconnect BUTI Arduino Box”
                self.connect_serial_action.setIcon(self.icon_disconnect)
                self.connect_serial_action.setText("Disconnect BUTI Arduino Box")

                # Disable the combo so they can’t switch mid‐stream
                self.serial_port_combobox.setEnabled(False)

            except Exception as e:
                log.exception("Failed to start SerialThread.")
                QMessageBox.critical(self, "Serial Error", str(e))
                if self._serial_thread:
                    self._serial_thread.deleteLater()
                self._serial_thread = None
                # Re‐enable the combo in case it got disabled
                self.serial_port_combobox.setEnabled(True)
                self._refresh_recording_button_states()

        # (2) Otherwise, a thread is already running → go into “DISCONNECT” branch
        else:
            log.info("Stopping SerialThread on user request...")
            try:
                self._serial_thread.stop()
            except Exception as e:
                log.error(f"Error while stopping SerialThread: {e}")
            try:
                if self._serial_thread is not None:
                    self._serial_thread.finished.disconnect(
                        self._handle_serial_thread_finished
                    )
            except TypeError:
                pass

            self._serial_start_sent = False
            self._device_run_active = False
            self.top_ctrl.set_run_state(False, connected=False)
            # Immediately flip QAction back to “Connect BUTI Arduino Box”
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect BUTI Arduino Box")

            # Re‐enable port-combo so they can pick another port
            self.serial_port_combobox.setEnabled(True)

            # Drop our reference so next click will “connect” again
            self._serial_thread = None

        # Finally, update the record‐button enable states (Start/Stop Recording)
        self._refresh_recording_button_states()

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"BUTI Arduino Box: {status}", 4000)
        self.serial_status_label.setText(f"Serial: {status}")

        normalized = status.lower()
        connected_flag = (
            self._serial_thread is not None
            and self._serial_thread.isRunning()
            and "disconnect" not in normalized
            and "error" not in normalized
        )
        if "disconnect" in normalized or "reconnect" in normalized:
            self._buti_settings = {}
            self._buti_settings_received_at = None
            self._box_observation.reset()
        self.top_ctrl.update_connection_status(status, connected_flag)
        self.top_ctrl.set_run_state(
            self._device_run_active, connected=connected_flag
        )
        if (
            ("disconnect" in normalized or "error" in normalized)
            and self._recording_state in {"preparing", "recording"}
        ):
            self._request_recording_stop(
                send_device_stop=False, reason="serial transport lost"
            )

        self._refresh_recording_button_states()

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        hint = "Check the cable and selected port, then try reconnecting."
        # Display brief guidance in the status bar as well
        self.statusBar().showMessage(
            f"Serial Error: {msg} — {hint}", 8000
        )
        self.serial_status_label.setText("Serial: Error")
        self._show_error_dialog("Serial Connection Error", f"{msg}\n\n{hint}")
        if self._recording_state in {"preparing", "recording"}:
            self._request_recording_stop(
                send_device_stop=False, reason="serial error"
            )
        # Also re-evaluate whether the recording buttons are enabled
        self._refresh_recording_button_states()

    @pyqtSlot(str)
    def _handle_recorder_error(self, msg: str):
        log.error(f"Recording error: {msg}")
        hint = "Check disk space and file permissions."
        self.statusBar().showMessage(
            f"Recording Error: {msg} — {hint}", 8000
        )
        self.recording_status_label.setText("Not Recording")
        self._show_error_dialog("Recording Error", f"{msg}\n\n{hint}")
        if self._recording_state in {"preparing", "recording"}:
            self._request_recording_stop(
                send_device_stop=(
                    self._serial_start_sent or self._device_run_active
                ),
                reason="recording error",
            )

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread finished signal received.")
        sender = self.sender()

        if self._serial_thread is not None and sender == self._serial_thread:
            # Clean up the thread object
            self._serial_thread.deleteLater()
            self._serial_thread = None
            self._serial_start_sent = False
            self._device_run_active = False
            self.top_ctrl.update_connection_status("Disconnected", False)

            # Immediately flip QAction back to “Connect BUTI Arduino Box”
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect BUTI Arduino Box")
            self.serial_port_combobox.setEnabled(True)

            log.info("SerialThread instance cleaned up.")
        else:
            log.warning(
                "Received 'finished' from an unknown/old SerialThread instance."
            )

        # Re‐evaluate “Start/Stop Recording” button states
        self._refresh_recording_button_states()

    @pyqtSlot()
    def _handle_serial_stream_started(self):
        """Begin a logical device run before its first sample is plotted."""

        self._device_run_active = True
        if self._recording_state == "preparing" and not self._serial_start_sent:
            self._request_recording_stop(send_device_stop=True, reason="box started before camera was ready")
            self.statusBar().showMessage("Recording cancelled: wait for BURST to start the Arduino. Use ZERO before retrying.", 10000)
            return
        self._box_observation.reset()
        self.top_ctrl.set_run_state(True, connected=True)
        if self.force_plot_widget is not None:
            self.force_plot_widget.clear_plot()
        self.statusBar().showMessage("New BUTI data run detected; plot cleared.", 3000)
        self._refresh_recording_button_states()

    @pyqtSlot(str)
    def _handle_serial_stream_stopped(self, reason: str):
        """React to natural silence without disconnecting the serial port."""

        self._device_run_active = False
        self._serial_start_sent = False
        serial_ready = self._serial_thread is not None and self._serial_thread.isRunning()
        self.top_ctrl.set_run_state(False, connected=serial_ready)
        if self._recording_state in {"preparing", "recording"}:
            self._request_recording_stop(
                send_device_stop=False, reason=f"serial {reason}"
            )
        self.statusBar().showMessage(
            f"BUTI data run complete ({reason}).", 5000
        )
        self._refresh_recording_button_states()

    @pyqtSlot(float, int, float, int, float)
    def _handle_new_serial_data(
        self, time_s: float, frame_idx: int, distance: float, cycle: int, force: float
    ):
        """
        Called whenever SerialThread emits a new BURST sample.
        Pushes data into the status panel, console log, and live plot.
        """
        try:
            self._box_observation.observe(time_s, frame_idx)
        except ValueError:
            self._box_observation.reset()
            self._box_observation.observe(time_s, frame_idx)
        # 1) Update TopControlPanel
        self.top_ctrl.update_burst_data(time_s, frame_idx, distance, cycle, force)
        self.top_ctrl.reset_btn.setToolTip(self._box_observation.description())

        # 2) Read the auto-scale checkboxes from PlotControlPanel
        ax = self.plot_control_panel.auto_x_cb.isChecked()
        ay = self.plot_control_panel.auto_y_cb.isChecked()

        # 3) Send the new sample to the plot widget
        self.force_plot_widget.update_plot(time_s, force, distance, cycle, ax, ay)

        # 4) Also log it to the console dock if visible
        if self.dock_console.isVisible():
            self.console_out_textedit.append(
                (
                    "BURST Data: Time={time:.3f}s, Frame={frame}, Distance={dist:.3f}, "
                    "Cycle={cycle}, Force={force:.2f}"
                ).format(
                    time=time_s,
                    frame=frame_idx,
                    dist=distance,
                    cycle=cycle,
                    force=force,
                )
            )

    # ──────────────────────────────────────────────────────────────
    # Recording Management
    # ──────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _toggle_recording(self):
        """Toggle recording on user request."""
        if self._recording_state in {"preparing", "recording"}:
            self._on_stop_recording()
        elif self._recording_state == "idle":
            self._on_start_recording()

    @pyqtSlot()
    def _on_start_recording(self):
        """Prepare a synchronized run and start the device only when ready."""
        if self._recording_state != "idle" or self._timing_transition:
            return
        if self._current_session_name is None:
            self._change_recording_session()
        if self._current_session_name is None:
            return
        if not self._run_silent_recording_preflight():
            self._refresh_recording_button_states()
            return
        self._preview_fps_at_recording = self._camera_rate_monitor.fps(time.monotonic())

        if self._recording_capture_mode == "box" and self._hardware_trigger_source:
            if not callable(getattr(self.camera_thread, "request_timing", None)):
                QMessageBox.information(self, "Camera synchronization unavailable",
                    "This camera connection supports preview but does not expose Arduino triggering. "
                    "Try the camera's vendor backend or a compatible Micro-Manager adapter.\n\n"
                    "If approximate video timing is acceptable, enable Acquisition > Advanced > "
                    "Allow approximate software pairing. Recording has not started.")
                return
            self._recording_state = "preparing"
            self._timing_transition = "arming"
            self.camera_control_panel.set_recording_state(True)
            self.camera_control_panel.setEnabled(False)
            self.resolution_combo.setEnabled(False)
            self.camera_info_panel.set_transform_controls_enabled(False)
            self.btn_start_camera.setEnabled(False)
            self._refresh_recording_button_states()
            self.recording_status_label.setText("Preparing camera…")
            self._timing_timer.start(35000)
            self.camera_thread.request_timing(self._hardware_trigger_source)
            return
        self._start_recording_files()

    @pyqtSlot(bool)
    def _on_camera_timing_ready(self, armed):
        if self.sender() is not self.camera_thread:
            return
        transition = self._timing_transition
        self._timing_timer.stop()
        self._camera_armed = armed
        self._timing_transition = ""
        self._last_camera_frame_monotonic = None
        self._camera_rate_monitor.reset()
        if transition == "arming" and self._recording_state == "preparing":
            if not armed or not self._run_silent_recording_preflight():
                self._recording_state = "idle"
                self._restore_camera_preview()
                return
            self._start_recording_files()
        elif transition == "preview":
            self.camera_control_panel.set_recording_state(False)
            self.camera_control_panel.setEnabled(True)
            self.camera_info_panel.set_transform_controls_enabled(True)
            self.btn_start_camera.setEnabled(True)
            self.camera_info_panel.set_status_message("Streaming")
            self.recording_status_label.setText("Not Recording")
            self._refresh_recording_button_states()
        self._update_camera_rate_status()

    def _restore_camera_preview(self):
        if self._camera_armed and self.camera_thread is not None and self.camera_thread.isRunning() and not self._closing:
            self._timing_transition = "preview"
            self.btn_start_camera.setEnabled(False)
            self._timing_timer.start(35000)
            self.camera_thread.request_timing("")
        else:
            self.camera_control_panel.set_recording_state(False)
            self.camera_control_panel.setEnabled(self.camera_thread is not None)
            self.camera_info_panel.set_transform_controls_enabled(True)
            self.btn_start_camera.setEnabled(True)
        self._refresh_recording_button_states()

    def _on_timing_timeout(self):
        if self._timing_transition:
            self._on_camera_error("The camera did not finish changing acquisition mode. "
                                  "Restart the camera before recording.", "camera-timing-timeout")

    def _start_recording_files(self):
        """Connect a fresh recorder only after the camera's preview stream is gone."""

        try:
            outdir = get_next_run_folder(self._current_session_name)
        except (OSError, ValueError) as exc:
            self._show_error_dialog(
                "Recording Folder Error",
                f"Unable to create the next Run folder:\n{exc}",
            )
            self._recording_state = "idle"
            self._restore_camera_preview()
            return
        self._current_run_folder = outdir
        self._last_recording_paths = {"tiff": None, "csv": None}
        self._recording_had_output = False
        self._last_recording_summary = None
        if hasattr(self, "playback_action"):
            self.playback_action.setEnabled(False)
        run_folder_name = os.path.basename(outdir)

        self._recorder_thread = QThread(self)
        self._recorder_worker = RecordingManager(
            output_dir=outdir,
            normalized_roi=self.camera_widget.normalized_roi(),
            mirror_horizontal=self._mirror_horizontal,
            mirror_vertical=self._mirror_vertical,
            acquisition_metadata=self._recording_acquisition_metadata(outdir),
        )
        self._recorder_worker.moveToThread(self._recorder_thread)
        self._recorder_thread.started.connect(self._recorder_worker.start_recording)
        self._recorder_worker.finished.connect(self._recorder_thread.quit)
        self._recorder_worker.finished.connect(self._on_recorder_worker_finished)
        self._recorder_worker.finished.connect(self._recorder_worker.deleteLater)
        self._recorder_thread.finished.connect(self._on_recorder_thread_finished)
        self._recorder_thread.finished.connect(self._recorder_thread.deleteLater)
        self._recorder_worker.ready_for_acquisition.connect(self._on_recorder_ready)
        self._recorder_worker.finalized.connect(self._on_recording_finalized)
        self._recorder_worker.error_occurred.connect(self._handle_recorder_error)
        self._recorder_worker.synchronization_lost.connect(self._on_recording_sync_lost)
        self._recorder_worker.warning_occurred.connect(
            self._handle_recorder_warning
        )
        self._serial_thread.data_ready.connect(self._recorder_worker.append_force)
        if self.camera_thread and self._recording_capture_mode != "force_only":
            self.camera_thread.frame_ready.connect(self._recorder_worker.append_frame)
        self._recording_state = "preparing"
        self._recorder_thread.start()
        if self.camera_control_panel:
            try:
                self.camera_control_panel.set_recording_state(True)
            except Exception:
                log.exception("Failed to set camera recording state to True")

        self.camera_info_panel.set_transform_controls_enabled(False)
        self.device_combo.setEnabled(False)
        self.resolution_combo.setEnabled(False)
        self.btn_start_camera.setEnabled(False)
        self._refresh_recording_button_states()
        self.recording_status_label.setText(f"Preparing → {run_folder_name}")
        log.info("Preparing recording in %s.", run_folder_name)

    @pyqtSlot(str)
    def _on_recording_sync_lost(self, message):
        self._request_recording_stop(send_device_stop=True, reason="camera fell behind force samples")
        self.statusBar().showMessage(message, 15000)
        log.warning(message)

    def _run_silent_recording_preflight(self) -> bool:
        """Return quietly when ready and explain every failed prerequisite at once."""

        now = time.monotonic()
        frame_age = (
            None
            if self._last_camera_frame_monotonic is None
            else max(0.0, now - self._last_camera_frame_monotonic)
        )
        rate_check = self._camera_rate_check()
        report = run_recording_preflight(
            serial_ready=(
                self._serial_thread is not None and self._serial_thread.isRunning()
            ),
            camera_ready=(
                self.camera_thread is not None and self.camera_thread.isRunning()
            ),
            camera_frame_age_s=frame_age,
            session_name=self._current_session_name,
            device_run_active=self._device_run_active,
            results_root=config.BURST_ROOT,
            minimum_free_gb=config.MIN_FREE_SPACE_GB,
            camera_rate_check=PreflightCheck("Camera rate", rate_check.passed, rate_check.detail),
            camera_required=self._recording_capture_mode != "force_only",
            hardware_armed=self._camera_armed and bool(self._hardware_trigger_source),
        )
        if report.passed:
            if self._camera_armed:
                return True
            measured = self._camera_rate_monitor.fps(now)
            if self._recording_capture_mode == "box" and measured is not None and measured < 9.5:
                answer = QMessageBox.warning(self, "Check box capture rate",
                    f"This camera is delivering {measured:.2f} FPS. The box capture rate is not yet verified.\n\n"
                    + RATE_SETUP + "\n\nBURST will save all force samples and follow trigger-counter changes. "
                    "If requested images fall behind, recording stops and the files are marked for review. "
                    "Exposure timing is not verified. Start recording with these settings?",
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                return answer == QMessageBox.Yes
            log.info("Recording prerequisites passed; box capture rate will be observed during acquisition.")
            return True

        failed_labels = "\n".join(f"• {check.label}: {check.detail}" for check in report.failures)
        if any(check.label == "Camera rate" for check in report.failures):
            self._show_camera_rate_help(failed_labels)
            return False
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Recording Not Ready")
        dialog.setText("BURST found a few things to fix before recording:")
        dialog.setInformativeText(failed_labels)
        dialog.setDetailedText(
            "\n".join(
                f"{'PASS' if check.passed else 'FAILED'} — {check.label}: {check.detail}"
                for check in report.checks
            )
        )
        dialog.exec_()
        return False

    def _recording_acquisition_metadata(self, outdir: str) -> dict:
        resolution = self.resolution_combo.currentData()
        if isinstance(resolution, (tuple, list)):
            resolution = list(resolution)
        elif resolution is not None:
            resolution = str(resolution)
        roi = self.camera_widget.normalized_roi()
        metadata = {
            "application": APP_NAME,
            "application_version": APP_VERSION,
            "session": self._current_session_name,
            "run": os.path.basename(outdir),
            "camera_resolution": resolution,
            "capture_mode": self._recording_capture_mode,
            "timing_mode": "force_only" if self._recording_capture_mode == "force_only" else ("external_trigger" if self._camera_armed else "software"),
            "trigger_configuration": getattr(self.camera_thread, "trigger_configuration", {}),
            "trigger_input": getattr(self.camera_thread, "trigger_input", None),
            "timing_validation": "not_verified_by_burst",
            "box_observation_before_run": self._box_observation.snapshot(),
            "first_sample_policy": "requires_zeroed_box" if self._camera_armed else "baseline_only_trigger_phase_unknown",
            "camera_rate": {
                "preview_requested_fps": DEFAULT_FPS,
                "recording_rate_source": "device_trigger_counter_transitions",
                "measured_delivery_fps": self._preview_fps_at_recording,
                "diagnostics": self.camera_thread.controller.diagnostics() if self.camera_thread else {},
                "pairing": "ordered_trigger_events" if self._camera_armed else "arrival_order_not_hardware_synchronized",
            },
            "frame_transform": {
                "normalized_roi": list(roi) if roi else None,
                "mirror_horizontal": self._mirror_horizontal,
                "mirror_vertical": self._mirror_vertical,
            },
        }
        if self._buti_settings:
            metadata["buti_settings"] = {
                **self._buti_settings,
                "received_at": self._buti_settings_received_at,
                "source": "serial_header",
            }
        return metadata

    @pyqtSlot(dict)
    def _handle_buti_settings_received(self, settings: dict) -> None:
        """Retain the latest BUTI header for the next run manifest."""

        # Replace a header snapshot: omitted fields must not survive as current settings.
        self._buti_settings = dict(settings)
        if self._recording_state in {"preparing", "recording"}:
            self._request_recording_stop(send_device_stop=True, reason="box settings header changed during recording")
        self._buti_settings_received_at = datetime.now().astimezone().isoformat()
        log.info("Received BUTI experiment header: %s", self._buti_settings)
        self.statusBar().showMessage("Box settings header received; unreported settings remain unknown.", 4000)

    @pyqtSlot()
    def _on_recorder_ready(self):
        """Send the start command to the BUTI Arduino Box when recording setup is done."""
        if self._recording_state != "preparing":
            return
        if self._recording_capture_mode == "box" and self._hardware_trigger_source and not self._camera_armed:
            self._request_recording_stop(send_device_stop=False, reason="camera is not armed")
            return
        self._serial_start_sent = self._send_serial_command(SERIAL_CMD_START)
        if self._serial_start_sent:
            self._recording_state = "recording"
            self._device_run_active = True
            self.top_ctrl.set_run_state(True, connected=True)
            self.recording_status_label.setText(
                f"Recording → {os.path.basename(self._current_run_folder)}"
            )
        else:
            self._request_recording_stop(
                send_device_stop=False, reason="unable to start device"
            )
        self._refresh_recording_button_states()

    @pyqtSlot()
    def _on_stop_recording(self):
        self._request_recording_stop(send_device_stop=True, reason="user request")

    def _request_recording_stop(self, *, send_device_stop: bool, reason: str):
        if self._recording_state not in {"preparing", "recording"}:
            return
        if self._recording_state == "preparing" and self._recorder_worker is None:
            self._timing_timer.stop()
            self._timing_transition = ""
            self._recording_state = "idle"
            if send_device_stop and self._device_run_active:
                self._send_serial_command(SERIAL_CMD_STOP)
            if self.camera_thread is not None:
                self.camera_thread.stop()
            self.recording_status_label.setText("Recording preparation cancelled")
            self.camera_info_panel.set_transform_controls_enabled(True)
            self._refresh_recording_button_states()
            return
        if send_device_stop:
            if self._send_serial_command(SERIAL_CMD_STOP):
                self._device_run_active = False
                self.top_ctrl.set_run_state(False, connected=True)
        self._serial_start_sent = False
        self._recording_state = "finalizing"
        if self._recorder_worker is not None:
            camera_active = self.camera_thread is not None and self.camera_thread.isRunning()
            method = "request_stop" if camera_active else "stop_recording"
            try:
                QMetaObject.invokeMethod(
                    self._recorder_worker, method, Qt.QueuedConnection
                )
            except RuntimeError:
                log.debug("Recorder was already destroyed while finalizing")
        self.recording_status_label.setText("Finalizing Recording…")
        self._refresh_recording_button_states()
        log.info("Stop recording requested (%s).", reason)

    @pyqtSlot(str, str, object)
    def _on_recording_finalized(self, csv_path: str, tiff_path: str, summary):
        self._recording_had_output = True
        self._last_recording_paths = {"csv": csv_path, "tiff": tiff_path}
        self._last_recording_summary = summary
        self._play_completion_sound()
        if hasattr(self, "playback_action"):
            self.playback_action.setEnabled(bool(tiff_path))

    def _run_recording_completion_prompts(self):
        """Collect rename and open-folder choices in one completion window."""

        self._prompt_recording_completion()

    def _prompt_recording_completion(self):
        csv_path = self._last_recording_paths.get("csv")
        tiff_path = self._last_recording_paths.get("tiff")
        if not csv_path:
            return
        current_base = os.path.basename(csv_path)
        if current_base.endswith("_force.csv"):
            current_base = current_base[: -len("_force.csv")]

        folder_path = self._current_run_folder or os.path.dirname(csv_path)
        dialog = RecordingCompletionDialog(
            current_base,
            os.path.basename(folder_path),
            summary=self._last_recording_summary,
            braid_application=find_braid_application() if tiff_path else None,
            has_images=bool(tiff_path),
            braid_icon_path=resource_path("ui", "icons", "braid.png"),
            parent=self,
        )
        dialog.open_folder_requested.connect(
            lambda: self._open_recording_folder(folder_path)
        )
        while True:
            if dialog.exec_() != QDialog.Accepted:
                return
            try:
                renamed_csv, renamed_tiff = rename_recording_pair(
                    csv_path,
                    tiff_path,
                    dialog.recording_name(),
                )
            except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
                QMessageBox.warning(self, "Unable to Rename Recording", str(exc))
                continue
            self._last_recording_paths = {
                "csv": renamed_csv,
                "tiff": renamed_tiff,
            }
            csv_path, tiff_path = renamed_csv, renamed_tiff
            try:
                update_manifest_file_names(folder_path, renamed_csv, renamed_tiff)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                log.warning("Unable to update recording manifest names: %s", exc)

            if dialog.completion_action() == "braid":
                if self._open_recording_in_braid(tiff_path):
                    return
                continue
            return

    def _open_recording_in_braid(self, tiff_path: str) -> bool:
        application = find_braid_application()
        if not application:
            QMessageBox.information(
                self,
                "BRAID Not Available",
                "BRAID is no longer available on this computer. The recording "
                "is safely saved and can still be opened later.",
            )
            return False
        program, arguments = braid_launch_command(application, tiff_path)
        try:
            started = QProcess.startDetached(program, arguments)
            if isinstance(started, tuple):
                started = started[0]
        except Exception as exc:
            log.exception("Unable to start BRAID")
            started = False
            detail = str(exc)
        else:
            detail = f"Command: {program} {' '.join(arguments)}"
        if started:
            self.statusBar().showMessage("Opened recording in BRAID.", 5000)
            return True
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Unable to Open BRAID")
        dialog.setText(
            "The recording is safely saved, but BRAID could not be started."
        )
        dialog.setDetailedText(detail)
        dialog.exec_()
        return False

    def check_for_recoverable_recordings(self) -> None:
        """Offer recovery for recordings left partial by an interrupted app run."""

        try:
            manifests = find_recoverable_manifests(config.BURST_ROOT)
        except OSError as exc:
            log.warning("Unable to scan for interrupted recordings: %s", exc)
            return
        for manifest_path in manifests:
            folder_path = os.path.dirname(manifest_path)
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Warning)
            dialog.setWindowTitle("Interrupted Recording Found")
            dialog.setText(
                "BURST found a recording that did not finish closing during an "
                "earlier app session."
            )
            dialog.setInformativeText(
                f"Run folder: {os.path.basename(folder_path)}\n\n"
                "Recover checks the partial CSV and TIFF, preserves all readable "
                "data, and marks the result for review."
            )
            recover_button = dialog.addButton("Recover Recording", QMessageBox.AcceptRole)
            open_button = dialog.addButton("Open Run Folder", QMessageBox.ActionRole)
            dialog.addButton("Later", QMessageBox.RejectRole)
            recover_button.setToolTip(
                "Validate the readable partial files and finalize them as a recovered recording"
            )
            open_button.setToolTip(
                "Inspect the interrupted recording files without changing them"
            )
            dialog.exec_()
            clicked = dialog.clickedButton()
            if clicked is open_button:
                self._open_recording_folder(folder_path)
                continue
            if clicked is not recover_button:
                continue
            try:
                csv_path, tiff_path, summary = recover_partial_recording(manifest_path)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                failure = QMessageBox(self)
                failure.setIcon(QMessageBox.Critical)
                failure.setWindowTitle("Recording Recovery Failed")
                failure.setText(
                    "BURST could not safely finalize this interrupted recording. "
                    "The partial files were left in place."
                )
                failure.setDetailedText(str(exc))
                failure.exec_()
                continue
            self._current_run_folder = folder_path
            self._last_recording_paths = {"csv": csv_path, "tiff": tiff_path}
            self._last_recording_summary = summary
            if hasattr(self, "playback_action"):
                self.playback_action.setEnabled(bool(tiff_path))
            self._prompt_recording_completion()

    @staticmethod
    def _open_recording_folder(path: str):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            log.error("Failed to open folder %s", path)

    @pyqtSlot(str)
    def _handle_recorder_warning(self, message: str):
        log.warning(message)
        self.statusBar().showMessage(message, 10000)

    @pyqtSlot()
    def _on_recorder_worker_finished(self):
        worker = self.sender()
        serial_thread = self._serial_thread
        camera_thread = self.camera_thread
        if serial_thread is not None and worker is not None:
            try:
                serial_thread.data_ready.disconnect(worker.append_force)
            except (TypeError, RuntimeError):
                pass
        if camera_thread is not None and worker is not None:
            try:
                camera_thread.frame_ready.disconnect(worker.append_frame)
            except (TypeError, RuntimeError):
                pass
        if self.camera_control_panel:
            self.camera_control_panel.set_recording_state(False)

    @pyqtSlot()
    def _on_recorder_thread_finished(self):
        thread = self.sender()
        if thread is self._recorder_thread:
            self._recorder_thread = None
            self._recorder_worker = None
        self._recording_state = "idle"
        self.recording_status_label.setText("Not Recording")
        self.camera_info_panel.set_transform_controls_enabled(True)
        camera_active = self.camera_thread is not None
        self.device_combo.setEnabled(not camera_active)
        self.resolution_combo.setEnabled(not camera_active)
        self.btn_start_camera.setEnabled(True)
        self.camera_info_panel.set_roi_available(
            self.camera_thread is not None and self.camera_thread.isRunning(),
            self.camera_widget.normalized_roi() is not None,
        )
        self._refresh_recording_button_states()
        self._restore_camera_preview()
        if self._recording_had_output:
            self._recording_had_output = False
            self._run_recording_completion_prompts()

    def _refresh_recording_button_states(self):
        """
        Update the recording toggle action to reflect the current acquisition state.
        """
        serial_ready = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        camera_ready = self.camera_thread is not None and self.camera_thread.isRunning()
        if self._recording_state in {"preparing", "recording"}:
            self.recording_action.setIcon(self.icon_record_stop)
            self.recording_action.setText("Stop R&ecording")
            self.recording_action.setShortcut(Qt.CTRL | Qt.Key_T)
            self.recording_action.setEnabled(True)
            self.top_ctrl.set_recording_state("recording", True)
        elif self._recording_state == "finalizing":
            self.recording_action.setIcon(self.icon_record_stop)
            self.recording_action.setText("Finalizing Recording…")
            self.recording_action.setEnabled(False)
            self.top_ctrl.set_recording_state("finalizing", False)
        else:
            self.recording_action.setIcon(self.icon_record_start)
            self.recording_action.setText("Start &Recording")
            self.recording_action.setShortcut(Qt.CTRL | Qt.Key_R)
            can_start = serial_ready and (camera_ready or self._recording_capture_mode == "force_only") and not self._device_run_active and not self._timing_transition
            self.recording_action.setEnabled(can_start)
            self.top_ctrl.set_recording_state("idle", can_start)
        if hasattr(self, "change_session_action"):
            self.change_session_action.setEnabled(self._recording_state == "idle" and not self._timing_transition)
        self.timing_action.setEnabled(self._recording_state == "idle" and not self._timing_transition)

    # ─── Window Close Cleanup ──────────────────────────────────────────────────
    def closeEvent(self, event):
        log.info("MainWindow closeEvent triggered.")

        # --- 1. ACCIDENTAL CLOSE PROTECTION ---
        if self._recorder_thread and self._recorder_thread.isRunning():
            # The app is still recording! Ask the user if they are sure.
            reply = QMessageBox.warning(
                self,
                "Recording in Progress",
                "A recording is currently active.\n\nAre you sure you want to exit? The recording will be forcefully stopped.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No  # Default to 'No' so they don't accidentally hit Enter and close it
            )

            if reply == QMessageBox.No:
                # User misclicked! Cancel the close event.
                log.info("App closure cancelled by user. Recording continues.")
                event.ignore()
                return  # Stop executing closeEvent, app stays open!

            # --- 2. INTENTIONAL CLOSE (EMERGENCY BRAKE) ---
            # If we reach here, the user clicked "Yes". We must tear down aggressively to save the files.
            log.info("User confirmed app closure. Stopping RecordingManager forcefully...")

            # Force immediate shutdown of files (bypass pending frame checks)
            QMetaObject.invokeMethod(
                self._recorder_worker, "stop_recording", Qt.QueuedConnection
            )

            # Explicitly tell the worker thread's event loop to quit
            self._recorder_thread.quit()

            # Wait up to 3 seconds for it to finish safely
            if not self._recorder_thread.wait(3000):
                log.warning("RecordingManager thread did not stop gracefully; forcing terminate.")
                try:
                    self._recorder_thread.terminate()
                except Exception:
                    pass
                self._recorder_thread.wait(500)

        # Now that the thread is done, delete both worker and thread objects if they exist
        if self._recorder_worker:
            try:
                self._recorder_worker.deleteLater()
            except Exception:
                pass
            self._recorder_worker = None

        if self._recorder_thread:
            try:
                self._recorder_thread.deleteLater()
            except Exception:
                pass
            self._recorder_thread = None

        self._closing = True
        checker = self.update_checker
        if checker is not None:
            try:
                if checker.isRunning():
                    checker.requestInterruption()
                    checker.wait(int((checker.timeout + 0.5) * 1000))
            except RuntimeError:
                pass
            self.update_checker = None

        # 2) Stop the serial thread (if it exists)
        if self._serial_thread:
            try:
                if self._serial_thread.isRunning():
                    log.info("Stopping SerialThread...")
                    self._serial_thread.stop()  # assume your SerialThread has a stop() method
                    if not self._serial_thread.wait(1500):
                        log.warning(
                            "SerialThread did not stop gracefully; forcing terminate."
                        )
                        try:
                            self._serial_thread.terminate()
                        except Exception:
                            pass
                        self._serial_thread.wait(500)

                try:
                    self._serial_thread.finished.disconnect(
                        self._handle_serial_thread_finished
                    )
                except TypeError:
                    pass

            except RuntimeError:
                # The QThread object might already be deleted; ignore
                pass
            finally:
                try:
                    self._serial_thread.deleteLater()
                except Exception:
                    pass
                self._serial_thread = None

        # A driver may take time to return. Never terminate a worker holding SDK resources.
        self.camera_control_panel.set_controller(None)
        cam_thread = self.camera_thread
        if cam_thread and cam_thread.isRunning():
            cam_thread.stop()
            if not cam_thread.wait(2000):
                log.warning("Waiting for camera cleanup before closing.")
                self._closing = False
                event.ignore()
                QTimer.singleShot(500, self.close)
                return
        self.device_combo.clear()
        # Drain queued frame payloads before shutting down the native libraries.
        QApplication.processEvents()
        self.camera_registry.close()

        # 5) Call the base implementation after all camera resources are released.
        log.info("All threads cleaned up. Proceeding with close.")
        super().closeEvent(event)

    def open_playback_window(self, ask_user=False):
        """Open a :class:`PlaybackWindow` with the last recording or ask for files."""
        tiff_path = self._last_recording_paths.get("tiff")
        csv_path = self._last_recording_paths.get("csv")
        if ask_user:
            tiff_path = csv_path = None
        elif tiff_path and csv_path and (
            not os.path.exists(tiff_path) or not os.path.exists(csv_path)
        ):
            tiff_path = csv_path = None

        self.playback_window = PlaybackWindow(tiff_path, csv_path, parent=self)
        self.playback_window.showMaximized()
