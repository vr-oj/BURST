import html
import logging
from typing import Callable, Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from ..style_constants import PANEL_STYLESHEET

from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGridLayout,
    QSizePolicy,
)

from ..widgets.metric_card import MetricCard
from utils.time_format import format_elapsed_time


log = logging.getLogger(__name__)

EM_DASH = "\u2014"


class TopControlPanel(QWidget):
    """BUTI Arduino Box status panel."""

    parameter_changed = pyqtSignal(str, object)
    zero_requested = pyqtSignal()
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    step_requested = pyqtSignal()
    record_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        panel = QFrame(self)
        panel.setProperty("cssClass", "panelCard")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root_layout.addWidget(panel)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(10)
        panel_layout.addLayout(content_row)

        identity_widget = QWidget()
        identity_widget.setMinimumWidth(218)
        identity_layout = QVBoxLayout(identity_widget)
        identity_layout.setContentsMargins(2, 0, 2, 0)
        identity_layout.setSpacing(4)

        title_label = QLabel("BUTI Arduino Box Status")
        title_label.setProperty("cssClass", "panelTitle")
        identity_layout.addWidget(title_label)

        identity_status_row = QHBoxLayout()
        identity_status_row.setContentsMargins(0, 0, 0, 0)
        identity_status_row.setSpacing(6)
        identity_layout.addLayout(identity_status_row)

        self.status_badge = QLabel()
        self.status_badge.setProperty("cssClass", "statusBadge")
        self.status_badge.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_badge.setTextFormat(Qt.RichText)
        identity_status_row.addWidget(self.status_badge)
        identity_status_row.addStretch()

        self.details_toggle = QPushButton("Details ▾")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setProperty("cssClass", "ghost")
        self.details_toggle.setToolTip("Show device connection and firmware details")
        self.details_toggle.toggled.connect(self.set_details_expanded)
        identity_status_row.addWidget(self.details_toggle)
        content_row.addWidget(identity_widget)

        hero_row = QHBoxLayout()
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.setSpacing(8)

        self.force_card = MetricCard("Force", self)
        self.distance_card = MetricCard("Distance", self)
        self.cycle_card = MetricCard("Cycle", self)
        self.time_card = MetricCard("Time", self)

        hero_row.addWidget(self.force_card)
        hero_row.addWidget(self.distance_card)
        hero_row.addWidget(self.cycle_card)
        hero_row.addWidget(self.time_card)

        content_row.addLayout(hero_row, 4)

        self.record_btn = QPushButton("●  Start Recording")
        self.record_btn.setProperty("cssClass", "record")
        self.record_btn.setProperty("recordState", "idle")
        self.record_btn.setMinimumWidth(170)
        self.record_btn.setMinimumHeight(58)
        self.record_btn.setToolTip("Start synchronized camera and BUTI recording (Ctrl+R)")
        self.record_btn.clicked.connect(self.record_requested.emit)
        content_row.addWidget(self.record_btn, 1)

        command_grid = QGridLayout()
        command_grid.setContentsMargins(0, 0, 0, 0)
        command_grid.setHorizontalSpacing(6)
        command_grid.setVerticalSpacing(6)
        content_row.addLayout(command_grid, 2)

        self.start_btn = QPushButton("Run Device")
        self.start_btn.setEnabled(False)
        self.start_btn.setToolTip("Run the BUTI device without saving recording files")
        self.start_btn.setProperty("cssClass", "primary")
        self.start_btn.clicked.connect(self.start_requested.emit)
        command_grid.addWidget(self.start_btn, 0, 0)

        self.stop_btn = QPushButton("Stop Device")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Stop the current BUTI device run")
        self.stop_btn.setProperty("cssClass", "primary")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        command_grid.addWidget(self.stop_btn, 0, 1, 1, 2)

        self.zero_btn = QPushButton("Home")
        self.zero_btn.setEnabled(False)
        self.zero_btn.setProperty("cssClass", "ghost")
        self.zero_btn.clicked.connect(self.zero_requested.emit)
        command_grid.addWidget(self.zero_btn, 1, 0)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setEnabled(False)
        self.reset_btn.setProperty("cssClass", "ghost")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        command_grid.addWidget(self.reset_btn, 1, 1)

        self.step_btn = QPushButton("Step")
        self.step_btn.setEnabled(False)
        self.step_btn.setProperty("cssClass", "ghost")
        self.step_btn.clicked.connect(self.step_requested.emit)
        command_grid.addWidget(self.step_btn, 1, 2)

        command_grid.setColumnStretch(0, 1)
        command_grid.setColumnStretch(1, 1)
        command_grid.setColumnStretch(2, 1)

        self.details_widget = QWidget()
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 2, 0, 0)
        details_layout.setSpacing(6)
        details_layout.addWidget(self._create_divider())

        detail_grid = QGridLayout()
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setHorizontalSpacing(24)
        detail_grid.setVerticalSpacing(5)
        detail_grid.setColumnStretch(1, 1)
        detail_grid.setColumnStretch(3, 1)

        details_layout.addLayout(detail_grid)
        panel_layout.addWidget(self.details_widget)

        self._detail_label_width = 108
        self.detail_values: Dict[str, QLabel] = {}

        self._add_detail_field(detail_grid, 0, 0, "Device Frame #", "frame")
        self._add_detail_field(
            detail_grid, 1, 0, "Device Time (MM:SS.hh)", "device_time"
        )
        self._add_detail_field(detail_grid, 2, 0, "Distance (mm)", "distance")

        self._add_detail_field(detail_grid, 0, 1, "Cycles", "cycles")
        self._add_detail_field(detail_grid, 1, 1, "Port / Device", "port_device")
        self._add_detail_field(detail_grid, 2, 1, "Firmware / ID", "firmware_id")

        self.set_details_expanded(False)

        self._apply_styles()
        self._set_status_badge("Disconnected", False)
        self.set_recording_state("idle", False)

    def set_details_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        self.details_widget.setVisible(expanded)
        self.details_toggle.blockSignals(True)
        self.details_toggle.setChecked(expanded)
        self.details_toggle.blockSignals(False)
        self.details_toggle.setText("Hide Details ▴" if expanded else "Details ▾")

    def set_recording_state(self, state: str, enabled: bool) -> None:
        """Keep the prominent acquisition button synchronized with app state."""

        state = state if state in {"idle", "recording", "finalizing"} else "idle"
        text = {
            "idle": "●  Start Recording",
            "recording": "■  Stop Recording",
            "finalizing": "Finalizing Recording…",
        }[state]
        tooltip = {
            "idle": "Start synchronized camera and BUTI recording (Ctrl+R)",
            "recording": "Stop and finalize the current recording (Ctrl+T)",
            "finalizing": "BURST is closing the synchronized recording files",
        }[state]
        self.record_btn.setText(text)
        self.record_btn.setToolTip(tooltip)
        self.record_btn.setEnabled(bool(enabled))
        self.record_btn.setProperty("recordState", state)
        self.record_btn.style().unpolish(self.record_btn)
        self.record_btn.style().polish(self.record_btn)
        self.record_btn.update()

    def _apply_styles(self):
        self.setStyleSheet(PANEL_STYLESHEET)

    def _create_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setProperty("cssClass", "panelDivider")
        return line

    def _add_detail_field(
        self,
        grid: QGridLayout,
        row: int,
        column: int,
        label_text: str,
        key: str,
    ) -> None:
        label = QLabel(label_text)
        label.setProperty("cssClass", "detailLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setFixedWidth(self._detail_label_width)

        value = QLabel(EM_DASH)
        value.setProperty("cssClass", "detailValue")
        value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        value.setTextFormat(Qt.RichText)

        grid.addWidget(label, row, column * 2)
        grid.addWidget(value, row, column * 2 + 1)

        self.detail_values[key] = value

    def _format_unit_html(self, value_text: str, unit_text: str) -> str:
        if not value_text:
            return EM_DASH

        safe_value = html.escape(value_text)
        if unit_text:
            safe_unit = html.escape(unit_text)
            return (
                f"{safe_value}<span style='opacity:0.8;font-size:0.82em;'> "
                f"{safe_unit}</span>"
            )
        return safe_value

    def _format_metric_value(
        self,
        value,
        unit: str = "",
        *,
        precision: Optional[int] = None,
        formatter: Optional[Callable[[object], str]] = None,
    ) -> str:
        if value is None:
            return EM_DASH

        try:
            if formatter is not None:
                value_text = formatter(value)
            elif precision is not None and isinstance(value, (int, float)):
                value_text = f"{value:.{precision}f}"
            else:
                value_text = str(value)
        except Exception:  # pragma: no cover - defensive
            log.debug("Failed to format metric value", exc_info=True)
            return EM_DASH

        return self._format_unit_html(value_text, unit)

    @staticmethod
    def _format_clock_time(seconds: float) -> str:
        return format_elapsed_time(seconds)

    def _set_detail_metric(
        self,
        key: str,
        value,
        unit: str = "",
        *,
        precision: Optional[int] = None,
        formatter: Optional[Callable[[object], str]] = None,
    ) -> None:
        label = self.detail_values.get(key)
        if not label:
            return

        html_value = self._format_metric_value(
            value,
            unit,
            precision=precision,
            formatter=formatter,
        )
        label.setText(html_value if html_value and html_value != EM_DASH else EM_DASH)

    def _set_detail_plain(self, key: str, text: Optional[str]) -> None:
        label = self.detail_values.get(key)
        if not label:
            return

        if not text:
            label.setText(EM_DASH)
        else:
            label.setText(html.escape(text))

    def _set_status_badge(self, text: str, connected: bool) -> None:
        status_text = text or "Disconnected"
        status_lower = status_text.lower()
        if connected:
            badge_color = "#3FD58F"
        elif "error" in status_lower or "fail" in status_lower:
            badge_color = "#E57373"
        else:
            badge_color = "#D6C832"

        neutral_color = "rgba(255, 255, 255, 0.8)"
        badge_html = (
            f"<span style='color:{badge_color}; font-size:12px;'>&#9679;</span> "
            f"<span style='color:{neutral_color};'>{html.escape(status_text)}</span>"
        )
        self.status_badge.setText(badge_html)

    def update_connection_status(self, text: str, connected: bool):
        """Show connection status with a colored state badge."""

        self._set_status_badge(text, connected)

        self.set_run_state(False, connected=connected)
        for btn in (self.reset_btn, self.zero_btn, self.step_btn):
            btn.setEnabled(connected)

    def set_run_state(self, running: bool, *, connected: bool = True) -> None:
        self.start_btn.setEnabled(bool(connected and not running))
        self.stop_btn.setEnabled(bool(connected and running))

    def update_burst_data(
        self,
        time_s: float,
        frame_idx: int,
        distance: float,
        cycle: int,
        force: float,
    ):
        """Update hero metrics and detail grid with the latest sample."""

        self.force_card.set_value(
            self._format_metric_value(force, "mN", precision=2)
        )
        self.distance_card.set_value(
            self._format_metric_value(distance, "mm", precision=2)
        )
        self.cycle_card.set_value(
            self._format_metric_value(
                cycle,
                "cyc",
                formatter=lambda v: f"{int(v):,}",
            )
        )
        self.time_card.set_value(
            self._format_metric_value(
                time_s,
                "min",
                formatter=self._format_clock_time,
            )
        )

        self._set_detail_metric(
            "frame",
            frame_idx,
            formatter=lambda v: f"{int(v):,}",
        )
        self._set_detail_metric(
            "device_time",
            time_s,
            formatter=self._format_clock_time,
        )
        self._set_detail_metric(
            "distance",
            distance,
            "mm",
            precision=3,
        )
        self._set_detail_metric(
            "cycles",
            cycle,
            "cycles",
            formatter=lambda v: f"{int(v):,}",
        )

    def update_device_metadata(
        self,
        *,
        port_device: Optional[str] = None,
        firmware_id: Optional[str] = None,
    ) -> None:
        """Update secondary device metadata fields."""

        if port_device is not None:
            self._set_detail_plain("port_device", port_device)

        if firmware_id is not None:
            self._set_detail_plain("firmware_id", firmware_id)
