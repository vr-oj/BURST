import html
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QPushButton,
)

from ..style_constants import PANEL_STYLESHEET
from ..widgets.metric_card import MetricCard

EM_DASH = "\u2014"


class CameraInfoPanel(QWidget):
    """Card-styled camera overview panel for the Camera tab."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._frame_count = 0
        self._fps_value: Optional[float] = None
        self._status_text = "Disconnected"

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        panel = QFrame(self)
        panel.setProperty("cssClass", "panelCard")
        root_layout.addWidget(panel)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Camera")
        title.setProperty("cssClass", "panelTitle")
        header.addWidget(title)
        header.addStretch()

        self.status_badge = QLabel()
        self.status_badge.setProperty("cssClass", "statusBadge")
        self.status_badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_badge.setTextFormat(Qt.RichText)
        header.addWidget(self.status_badge)

        panel_layout.addLayout(header)

        hero_row = QHBoxLayout()
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.setSpacing(12)

        self.fps_card = MetricCard("FPS")
        self.frame_card = MetricCard("Frame")
        self.resolution_card = MetricCard("Resolution", uppercase_label=False)

        hero_row.addWidget(self.fps_card)
        hero_row.addWidget(self.frame_card)
        hero_row.addWidget(self.resolution_card)
        panel_layout.addLayout(hero_row)
        panel_layout.addWidget(self._create_divider())

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        panel_layout.addLayout(grid)

        label_width = 132

        device_label = QLabel("Device")
        device_label.setProperty("cssClass", "detailLabel")
        device_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        device_label.setFixedWidth(label_width)
        grid.addWidget(device_label, 0, 0)

        self.device_combo = QComboBox()
        self.device_combo.setProperty("cssClass", "monoInput")
        grid.addWidget(self.device_combo, 0, 1)

        resolution_label = QLabel("Resolution")
        resolution_label.setProperty("cssClass", "detailLabel")
        resolution_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        resolution_label.setFixedWidth(label_width)
        grid.addWidget(resolution_label, 1, 0)

        resolution_row = QHBoxLayout()
        resolution_row.setContentsMargins(0, 0, 0, 0)
        resolution_row.setSpacing(8)

        resolution_widget = QWidget()
        resolution_widget.setLayout(resolution_row)

        self.resolution_combo = QComboBox()
        self.resolution_combo.setProperty("cssClass", "monoInput")
        resolution_row.addWidget(self.resolution_combo, 1)

        resolution_row.addStretch()

        self.start_button = QPushButton("Start Camera")
        self.start_button.setProperty("cssClass", "primary")
        resolution_row.addWidget(self.start_button)

        grid.addWidget(resolution_widget, 1, 1)

        panel_layout.addWidget(self._create_divider())

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)

        self.status_message = QLabel("Waiting for camera…")
        self.status_message.setProperty("cssClass", "detailValue")
        self.status_message.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        status_row.addWidget(self.status_message)
        status_row.addStretch()

        panel_layout.addLayout(status_row)

        self.setStyleSheet(PANEL_STYLESHEET)
        self.update_status("Disconnected")
        self.reset_metrics()

    def _create_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setProperty("cssClass", "panelDivider")
        return line

    def reset_metrics(self) -> None:
        self._frame_count = 0
        self._fps_value = None
        self.fps_card.set_value(EM_DASH)
        self.frame_card.set_value(EM_DASH)
        self.resolution_card.set_value(EM_DASH)

    def update_status(self, text: str, *, state: Optional[str] = None) -> None:
        state = (state or "").lower()
        status_text = text or "Disconnected"
        if not state:
            lowered = status_text.lower()
            if "error" in lowered or "fail" in lowered:
                state = "error"
            elif "connect" in lowered and "connected" not in lowered:
                state = "warning"
            elif lowered == "connected":
                state = "connected"
            else:
                state = "idle"

        color = {
            "connected": "#3FD58F",
            "warning": "#D6C832",
            "error": "#E57373",
        }.get(state, "#D6C832")

        neutral = "rgba(255, 255, 255, 0.82)"
        badge_html = (
            f"<span style='color:{color}; font-size:12px;'>●</span> "
            f"<span style='color:{neutral};'>{html.escape(status_text)}</span>"
        )
        self.status_badge.setText(badge_html)
        self._status_text = status_text

    def set_status_message(self, message: str) -> None:
        self.status_message.setText(message or EM_DASH)

    def set_fps(self, value: Optional[float], unit: str = "fps") -> None:
        self._fps_value = value
        formatted = self._format_value(value, unit=unit, precision=1)
        self.fps_card.set_value(formatted)

    def set_frame_count(self, count: int) -> None:
        self._frame_count = max(0, int(count))
        formatted = self._format_value(self._frame_count, formatter=lambda v: f"{int(v):,}")
        self.frame_card.set_value(formatted)

    def increment_frame_count(self) -> int:
        self._frame_count += 1
        self.set_frame_count(self._frame_count)
        return self._frame_count

    def frame_count(self) -> int:
        return self._frame_count

    def set_resolution(self, text: Optional[str]) -> None:
        if not text:
            self.resolution_card.set_value(EM_DASH)
        else:
            safe_text = html.escape(text)
            self.resolution_card.set_value(safe_text)

    def status_text(self) -> str:
        return self._status_text

    def _format_value(
        self,
        value: Optional[float],
        *,
        unit: str = "",
        precision: Optional[int] = None,
        formatter=None,
    ) -> str:
        if value is None:
            return EM_DASH

        try:
            if formatter is not None:
                value_text = formatter(value)
            elif precision is not None:
                value_text = f"{float(value):.{precision}f}"
            else:
                value_text = str(value)
        except Exception:
            return EM_DASH

        safe_value = html.escape(value_text)
        if unit:
            safe_unit = html.escape(unit)
            return (
                f"{safe_value}<span style='opacity:0.8;font-size:0.82em;'> "
                f"{safe_unit}</span>"
            )
        return safe_value
