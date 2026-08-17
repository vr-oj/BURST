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
        panel_layout.addWidget(self.advanced_controls)

        panel_layout.addWidget(self._create_divider())

        transform_grid = QGridLayout()
        transform_grid.setContentsMargins(0, 0, 0, 0)
        transform_grid.setHorizontalSpacing(8)
        transform_grid.setVerticalSpacing(6)
        transform_grid.setColumnStretch(3, 1)
        panel_layout.addLayout(transform_grid)

        transform_label = QLabel("Orientation")
        transform_label.setProperty("cssClass", "detailLabel")
        transform_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        transform_label.setFixedWidth(92)
        transform_grid.addWidget(transform_label, 0, 0)

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
        self.roi_button = QPushButton("Draw ROI")
        self.roi_button.setProperty("cssClass", "ghost")
        self.roi_button.setEnabled(False)
        self.clear_roi_button = QPushButton("Clear ROI")
        self.clear_roi_button.setProperty("cssClass", "ghost")
        self.clear_roi_button.setEnabled(False)
        transform_grid.addWidget(self.mirror_horizontal_cb, 0, 1)
        transform_grid.addWidget(self.mirror_vertical_cb, 0, 2)

        roi_label = QLabel("Recording ROI")
        roi_label.setProperty("cssClass", "detailLabel")
        roi_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        roi_label.setFixedWidth(92)
        transform_grid.addWidget(roi_label, 1, 0)
        transform_grid.addWidget(self.roi_button, 1, 1)
        transform_grid.addWidget(self.clear_roi_button, 1, 2)

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
