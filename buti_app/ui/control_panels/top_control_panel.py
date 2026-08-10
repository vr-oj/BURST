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

    def __init__(self, parent=None):
        super().__init__(parent)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        panel = QFrame(self)
        panel.setProperty("cssClass", "panelCard")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        root_layout.addWidget(panel)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_label = QLabel("BUTI Arduino Box Status")
        title_label.setProperty("cssClass", "panelTitle")
        header_row.addWidget(title_label)

        header_row.addStretch()

        self.status_badge = QLabel()
        self.status_badge.setProperty("cssClass", "statusBadge")
        self.status_badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_badge.setTextFormat(Qt.RichText)
        header_row.addWidget(self.status_badge)

        panel_layout.addLayout(header_row)

        hero_row = QHBoxLayout()
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.setSpacing(12)

        self.force_card = MetricCard("Force", self)
        self.distance_card = MetricCard("Distance", self)
        self.cycle_card = MetricCard("Cycle", self)
        self.time_card = MetricCard("Time", self)

        hero_row.addWidget(self.force_card)
        hero_row.addWidget(self.distance_card)
        hero_row.addWidget(self.cycle_card)
        hero_row.addWidget(self.time_card)

        panel_layout.addLayout(hero_row)
        panel_layout.addWidget(self._create_divider())

        detail_grid = QGridLayout()
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setHorizontalSpacing(24)
        detail_grid.setVerticalSpacing(8)
        detail_grid.setColumnStretch(1, 1)
        detail_grid.setColumnStretch(3, 1)

        panel_layout.addLayout(detail_grid)

        self._detail_label_width = 132
        self.detail_values: Dict[str, QLabel] = {}

        self._add_detail_field(detail_grid, 0, 0, "Device Frame #", "frame")
        self._add_detail_field(detail_grid, 1, 0, "Device Time (s)", "device_time")
        self._add_detail_field(detail_grid, 2, 0, "Distance (mm)", "distance")

        self._add_detail_field(detail_grid, 0, 1, "Cycles", "cycles")
        self._add_detail_field(detail_grid, 1, 1, "Port / Device", "port_device")
        self._add_detail_field(detail_grid, 2, 1, "Firmware / ID", "firmware_id")

        panel_layout.addWidget(self._create_divider())

        command_layout = QHBoxLayout()
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(8)
        command_layout.addStretch()
        panel_layout.addLayout(command_layout)

        self.start_btn = QPushButton("Start")
        self.start_btn.setEnabled(False)
        self.start_btn.setProperty("cssClass", "primary")
        self.start_btn.clicked.connect(self.start_requested.emit)
        command_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setProperty("cssClass", "primary")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        command_layout.addWidget(self.stop_btn)

        self.zero_btn = QPushButton("Home")
        self.zero_btn.setEnabled(False)
        self.zero_btn.setProperty("cssClass", "ghost")
        self.zero_btn.clicked.connect(self.zero_requested.emit)
        command_layout.addWidget(self.zero_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setEnabled(False)
        self.reset_btn.setProperty("cssClass", "ghost")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        command_layout.addWidget(self.reset_btn)

        self.step_btn = QPushButton("Step")
        self.step_btn.setEnabled(False)
        self.step_btn.setProperty("cssClass", "ghost")
        self.step_btn.clicked.connect(self.step_requested.emit)
        command_layout.addWidget(self.step_btn)

        self._apply_styles()
        self._set_status_badge("Disconnected", False)

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
        if seconds is None:
            return EM_DASH

        total = max(float(seconds), 0.0)
        minutes = int(total // 60)
        remaining = total - minutes * 60
        remaining = round(remaining, 1)

        if remaining >= 60.0:
            minutes += 1
            remaining = 0.0

        whole_seconds = int(remaining)
        tenths = int(round((remaining - whole_seconds) * 10))
        if tenths == 10:
            whole_seconds += 1
            tenths = 0
            if whole_seconds == 60:
                minutes += 1
                whole_seconds = 0

        return f"{minutes:02d}:{whole_seconds:02d}.{tenths}"

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

        for btn in (self.start_btn, self.stop_btn, self.reset_btn, self.zero_btn, self.step_btn):
            btn.setEnabled(connected)

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
                "s",
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
            "s",
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
