"""Plot control panel with styled layout."""

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QCheckBox,
    QDoubleSpinBox,
    QPushButton,
    QSizePolicy,
)

from ..style_constants import PANEL_STYLESHEET
from utils.config import PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX

log = logging.getLogger(__name__)

class PlotControlPanel(QWidget):
    """Panel with controls for the live force-versus-time plot."""

    autoscale_x_changed = pyqtSignal(bool)
    autoscale_y_changed = pyqtSignal(bool)
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    reset_zoom_requested = pyqtSignal()
    export_plot_image_requested = pyqtSignal()
    clear_plot_requested = pyqtSignal()

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
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title = QLabel("Plot Controls")
        title.setProperty("cssClass", "panelTitle")
        header_row.addWidget(title)

        subtitle = QLabel("Live force vs. time")
        subtitle.setProperty("cssClass", "detailLabel")
        header_row.addWidget(subtitle)
        header_row.addStretch()

        self.auto_summary_label = QLabel()
        self.auto_summary_label.setProperty("cssClass", "axisState")
        self.auto_summary_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_row.addWidget(self.auto_summary_label)

        panel_layout.addLayout(header_row)

        self.x_min = self._create_spinbox(
            decimals=3, enabled=False, suffix=" s"
        )
        self.x_max = self._create_spinbox(
            decimals=3, enabled=False, suffix=" s"
        )

        self.auto_x_cb = QCheckBox("Auto scale")
        self.auto_x_cb.setChecked(True)
        self.auto_x_cb.setProperty("cssClass", "muted")

        self.y_min = self._create_spinbox(
            decimals=1, enabled=True, suffix=" mN"
        )
        self.y_max = self._create_spinbox(
            decimals=1, enabled=True, suffix=" mN"
        )
        self.y_min.setValue(PLOT_DEFAULT_Y_MIN)
        self.y_max.setValue(PLOT_DEFAULT_Y_MAX)

        self.auto_y_cb = QCheckBox("Auto scale")
        self.auto_y_cb.setChecked(False)
        self.auto_y_cb.setProperty("cssClass", "muted")

        self.advanced_controls = QWidget()
        advanced_layout = QHBoxLayout(self.advanced_controls)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)

        self.x_axis_card, self.x_mode_label = self._build_axis_card(
            axis="X AXIS",
            quantity="Time",
            min_spin=self.x_min,
            max_spin=self.x_max,
            auto_widget=self.auto_x_cb,
        )
        self.y_axis_card, self.y_mode_label = self._build_axis_card(
            axis="Y AXIS",
            quantity="Force",
            min_spin=self.y_min,
            max_spin=self.y_max,
            auto_widget=self.auto_y_cb,
        )
        advanced_layout.addWidget(self.x_axis_card, 1)
        advanced_layout.addWidget(self.y_axis_card, 1)

        panel_layout.addWidget(self.advanced_controls, 1)
        panel_layout.addWidget(self._create_divider())

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(6)

        self.range_label = QLabel()
        self.range_label.setProperty("cssClass", "detailValue")
        self.range_label.setMinimumWidth(0)
        self.range_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        footer_row.addWidget(self.range_label, 1)

        self.reset_btn = QPushButton("Reset View")
        self.reset_btn.setProperty("cssClass", "ghost")
        footer_row.addWidget(self.reset_btn)

        self.clear_plot_btn = QPushButton("Clear Data")
        self.clear_plot_btn.setProperty("cssClass", "ghost")
        footer_row.addWidget(self.clear_plot_btn)

        self.export_img_btn = QPushButton("Export Image")
        self.export_img_btn.setProperty("cssClass", "primary")
        footer_row.addWidget(self.export_img_btn)

        panel_layout.addLayout(footer_row)

        self._wire_events()
        self.setStyleSheet(PANEL_STYLESHEET)
        self._refresh_range_preview()

    def _wire_events(self) -> None:
        self.auto_x_cb.toggled.connect(self._on_auto_x_toggled)
        self.auto_x_cb.toggled.connect(self.autoscale_x_changed.emit)

        self.auto_y_cb.toggled.connect(self._on_auto_y_toggled)
        self.auto_y_cb.toggled.connect(self.autoscale_y_changed.emit)

        self.x_min.valueChanged.connect(self._emit_x_limits)
        self.x_max.valueChanged.connect(self._emit_x_limits)

        self.y_min.valueChanged.connect(self._emit_y_limits)
        self.y_max.valueChanged.connect(self._emit_y_limits)

        self.reset_btn.clicked.connect(self.reset_zoom_requested.emit)
        self.clear_plot_btn.clicked.connect(self.clear_plot_requested.emit)
        self.export_img_btn.clicked.connect(self.export_plot_image_requested.emit)
    def _create_spinbox(
        self,
        *,
        decimals: int,
        enabled: bool,
        suffix: str,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(-1_000_000, 1_000_000)
        spin.setEnabled(enabled)
        spin.setSuffix(suffix)
        spin.setProperty("cssClass", "monoInput")
        spin.setMinimumWidth(104)
        spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        spin.setKeyboardTracking(False)
        return spin

    def _build_axis_card(
        self,
        *,
        axis: str,
        quantity: str,
        min_spin: QDoubleSpinBox,
        max_spin: QDoubleSpinBox,
        auto_widget: QCheckBox,
    ) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setProperty("cssClass", "subCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(7)

        axis_label = QLabel(axis)
        axis_label.setProperty("cssClass", "sectionLabel")
        header.addWidget(axis_label)

        quantity_label = QLabel(quantity)
        quantity_label.setProperty("cssClass", "detailLabel")
        header.addWidget(quantity_label)
        header.addStretch()
        header.addWidget(auto_widget)
        layout.addLayout(header)

        limits = QGridLayout()
        limits.setContentsMargins(0, 0, 0, 0)
        limits.setHorizontalSpacing(8)
        limits.setVerticalSpacing(3)
        limits.setColumnStretch(0, 1)
        limits.setColumnStretch(1, 1)

        min_label = QLabel("MINIMUM")
        min_label.setProperty("cssClass", "microLabel")
        limits.addWidget(min_label, 0, 0)

        max_label = QLabel("MAXIMUM")
        max_label.setProperty("cssClass", "microLabel")
        limits.addWidget(max_label, 0, 1)

        limits.addWidget(min_spin, 1, 0)
        limits.addWidget(max_spin, 1, 1)
        layout.addLayout(limits)

        layout.addStretch()
        mode_label = QLabel()
        mode_label.setProperty("cssClass", "axisState")
        layout.addWidget(mode_label)

        return card, mode_label

    def _create_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setProperty("cssClass", "panelDivider")
        return line

    def _on_auto_x_toggled(self, checked: bool) -> None:
        self.x_min.setEnabled(not checked)
        self.x_max.setEnabled(not checked)
        self._refresh_range_preview()

    def _on_auto_y_toggled(self, checked: bool) -> None:
        self.y_min.setEnabled(not checked)
        self.y_max.setEnabled(not checked)
        self._refresh_range_preview()

    def _emit_x_limits(self) -> None:
        if not self.auto_x_cb.isChecked():
            self.x_axis_limits_changed.emit(self.x_min.value(), self.x_max.value())
        self._refresh_range_preview()

    def _emit_y_limits(self) -> None:
        if not self.auto_y_cb.isChecked():
            self.y_axis_limits_changed.emit(self.y_min.value(), self.y_max.value())
        self._refresh_range_preview()

    def _refresh_range_preview(self) -> None:
        x_min = self.x_min.value()
        x_max = self.x_max.value()
        y_min = self.y_min.value()
        y_max = self.y_max.value()

        x_auto = self.auto_x_cb.isChecked()
        y_auto = self.auto_y_cb.isChecked()
        x_range = "Auto" if x_auto else f"{x_min:.3f}–{x_max:.3f} s"
        y_range = "Auto" if y_auto else f"{y_min:.1f}–{y_max:.1f} mN"
        self.range_label.setText(
            f"Active view  ·  X {x_range}  ·  Y {y_range}"
        )
        self.auto_summary_label.setText(
            f"X {'AUTO' if x_auto else 'MANUAL'}  ·  "
            f"Y {'AUTO' if y_auto else 'MANUAL'}"
        )
        self.x_mode_label.setText(
            "Follows elapsed recording time" if x_auto else "Uses the limits above"
        )
        self.y_mode_label.setText(
            "Fits incoming force data" if y_auto else "Uses the limits above"
        )

    def is_autoscale_x(self) -> bool:
        return self.auto_x_cb.isChecked()

    def is_autoscale_y(self) -> bool:
        return self.auto_y_cb.isChecked()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.auto_x_cb.setEnabled(enabled)
        self.auto_y_cb.setEnabled(enabled)
        self.x_min.setEnabled(enabled and not self.auto_x_cb.isChecked())
        self.x_max.setEnabled(enabled and not self.auto_x_cb.isChecked())
        self.y_min.setEnabled(enabled and not self.auto_y_cb.isChecked())
        self.y_max.setEnabled(enabled and not self.auto_y_cb.isChecked())
        self.reset_btn.setEnabled(enabled)
        self.clear_plot_btn.setEnabled(enabled)
        self.export_img_btn.setEnabled(enabled)
