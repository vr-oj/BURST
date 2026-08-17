import html
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QSizePolicy,
)

from ..style_constants import PANEL_STYLESHEET

EM_DASH = "\u2014"


class CameraInfoPanel(QWidget):
    """Visible image controls, orientation, and camera status card."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._frame_count = 0
        self._fps_value: Optional[float] = None
        self._resolution_text: Optional[str] = None
        self._status_text = "Disconnected"
        self._has_roi = False
        self._embedded_control_panel = None

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        panel = QFrame(self)
        panel.setProperty("cssClass", "panelCard")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root_layout.addWidget(panel)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Camera")
        title.setProperty("cssClass", "panelTitle")
        header.addWidget(title)

        self.status_badge = QLabel()
        self.status_badge.setProperty("cssClass", "statusBadge")
        self.status_badge.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_badge.setTextFormat(Qt.RichText)
        header.addWidget(self.status_badge)
        header.addStretch()

        self.status_message = QLabel("Waiting for camera…")
        self.status_message.setProperty("cssClass", "detailValue")
        self.status_message.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.status_message)

        self.stream_details = QLabel(EM_DASH)
        self.stream_details.setProperty("cssClass", "detailValue")
        self.stream_details.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.stream_details)

        panel_layout.addLayout(header)
        panel_layout.addWidget(self._create_divider())

        self.settings_body_layout = QHBoxLayout()
        self.settings_body_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_body_layout.setSpacing(12)
        panel_layout.addLayout(self.settings_body_layout)

        self.advanced_controls = QWidget()
        controls_layout = QVBoxLayout(self.advanced_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        controls_header = QLabel("IMAGE SETTINGS")
        controls_header.setProperty("cssClass", "microLabel")
        controls_layout.addWidget(controls_header)
        self.embedded_controls_layout = QVBoxLayout()
        self.embedded_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.embedded_controls_layout.setSpacing(0)
        controls_layout.addLayout(self.embedded_controls_layout)
        self.settings_body_layout.addWidget(self.advanced_controls, 7)

        self.capture_options_card = QFrame()
        self.capture_options_card.setProperty("cssClass", "subCard")
        self.capture_options_card.setMinimumWidth(220)
        self.capture_options_card.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Expanding
        )
        options_layout = QVBoxLayout(self.capture_options_card)
        options_layout.setContentsMargins(10, 8, 10, 8)
        options_layout.setSpacing(6)
        self.settings_body_layout.addWidget(self.capture_options_card, 3)

        orientation_label = QLabel("ORIENTATION")
        orientation_label.setProperty("cssClass", "sectionLabel")
        options_layout.addWidget(orientation_label)

        self.mirror_horizontal_cb = QCheckBox("Flip Left/Right")
        self.mirror_vertical_cb = QCheckBox("Flip Up/Down")
        self.mirror_horizontal_cb.setProperty("cssClass", "muted")
        self.mirror_vertical_cb.setProperty("cssClass", "muted")
        transform_help = (
            "Applies to the live preview and new TIFF recordings for this app "
            "session. Camera orientation starts unflipped each time BURST opens."
        )
        self.mirror_horizontal_cb.setToolTip(transform_help)
        self.mirror_vertical_cb.setToolTip(transform_help)

        orientation_row = QHBoxLayout()
        orientation_row.setContentsMargins(0, 0, 0, 0)
        orientation_row.setSpacing(10)
        orientation_row.addWidget(self.mirror_horizontal_cb)
        orientation_row.addWidget(self.mirror_vertical_cb)
        orientation_row.addStretch()
        options_layout.addLayout(orientation_row)

        options_layout.addWidget(self._create_divider())

        roi_label = QLabel("RECORDING ROI")
        roi_label.setProperty("cssClass", "sectionLabel")
        options_layout.addWidget(roi_label)

        self.roi_button = QPushButton("Draw ROI")
        self.roi_button.setProperty("cssClass", "ghost")
        self.roi_button.setEnabled(False)
        self.clear_roi_button = QPushButton("Clear ROI")
        self.clear_roi_button.setProperty("cssClass", "ghost")
        self.clear_roi_button.setEnabled(False)

        roi_row = QHBoxLayout()
        roi_row.setContentsMargins(0, 0, 0, 0)
        roi_row.setSpacing(6)
        roi_row.addWidget(self.roi_button, 1)
        roi_row.addWidget(self.clear_roi_button, 1)
        options_layout.addLayout(roi_row)
        options_layout.addStretch()

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
        self._resolution_text = None
        self._refresh_stream_details()

    def set_control_panel(self, panel: QWidget) -> None:
        """Embed the hardware image controls into this single camera card."""

        if self._embedded_control_panel is panel:
            return
        if self._embedded_control_panel is not None:
            self.embedded_controls_layout.removeWidget(self._embedded_control_panel)
        self._embedded_control_panel = panel
        panel.setParent(self)
        self.embedded_controls_layout.addWidget(panel)

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
        del unit
        self._fps_value = value
        self._refresh_stream_details()

    def set_frame_count(self, count: int) -> None:
        self._frame_count = max(0, int(count))
        self._refresh_stream_details()

    def increment_frame_count(self) -> int:
        self._frame_count += 1
        self.set_frame_count(self._frame_count)
        return self._frame_count

    def frame_count(self) -> int:
        return self._frame_count

    def set_resolution(self, text: Optional[str]) -> None:
        self._resolution_text = text or None
        self._refresh_stream_details()

    def _refresh_stream_details(self) -> None:
        details = []
        if self._resolution_text:
            details.append(self._resolution_text)
        if self._fps_value is not None:
            details.append(f"{float(self._fps_value):.1f} fps")
        if self._frame_count:
            details.append(f"Frame {self._frame_count:,}")
        self.stream_details.setText("  •  ".join(details) if details else EM_DASH)

    def status_text(self) -> str:
        return self._status_text

    def set_roi_available(self, available: bool, has_roi: bool = False) -> None:
        self._has_roi = bool(has_roi)
        self.roi_button.setEnabled(bool(available))
        self.roi_button.setText("Edit ROI" if self._has_roi else "Draw ROI")
        self.clear_roi_button.setEnabled(bool(available and self._has_roi))

    def set_transform_controls_enabled(self, enabled: bool) -> None:
        self.mirror_horizontal_cb.setEnabled(enabled)
        self.mirror_vertical_cb.setEnabled(enabled)
        self.set_roi_available(
            enabled and self._status_text == "Connected",
            self._has_roi,
        )
