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
)

from ..style_constants import PANEL_STYLESHEET
from utils.config import PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX

log = logging.getLogger(__name__)

CHECK_MARK = "✓"
CROSS_MARK = "✗"


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
        root_layout.addWidget(panel)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title = QLabel("Plot Controls")
        title.setProperty("cssClass", "panelTitle")
        header_row.addWidget(title)
        header_row.addStretch()



        panel_layout.addLayout(header_row)

        range_widget = QWidget()
        range_layout = QVBoxLayout(range_widget)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(2)

        self.range_label = QLabel()
        self.range_label.setProperty("cssClass", "detailValue")
        range_layout.addWidget(self.range_label)

        self.auto_summary_label = QLabel()
        self.auto_summary_label.setProperty("cssClass", "detailLabel")
        range_layout.addWidget(self.auto_summary_label)

        panel_layout.addWidget(range_widget)
        panel_layout.addWidget(self._create_divider())

        self._label_width = 132

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(1, 1)
        panel_layout.addLayout(grid)

        self.x_min = self._create_spinbox(decimals=3, enabled=False)
        self.x_max = self._create_spinbox(decimals=3, enabled=False)
        x_widget = self._build_limit_editor(self.x_min, self.x_max, unit="s")

        self.auto_x_cb = QCheckBox("Auto")
        self.auto_x_cb.setChecked(True)
        self.auto_x_cb.setProperty("cssClass", "muted")

        self._add_limit_row(grid, 0, "X Limits", x_widget, self.auto_x_cb)

        self.y_min = self._create_spinbox(decimals=1, enabled=True)
        self.y_max = self._create_spinbox(decimals=1, enabled=True)
        self.y_min.setValue(PLOT_DEFAULT_Y_MIN)
        self.y_max.setValue(PLOT_DEFAULT_Y_MAX)
        y_widget = self._build_limit_editor(self.y_min, self.y_max, unit="mN")

        self.auto_y_cb = QCheckBox("Auto")
        self.auto_y_cb.setChecked(False)
        self.auto_y_cb.setProperty("cssClass", "muted")

        self._add_limit_row(grid, 1, "Y Limits", y_widget, self.auto_y_cb)

        panel_layout.addWidget(self._create_divider())

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.addStretch()
        panel_layout.addLayout(footer)

        self.reset_btn = QPushButton("Reset View")
        self.reset_btn.setProperty("cssClass", "ghost")
        footer.addWidget(self.reset_btn)

        self.clear_plot_btn = QPushButton("Clear Data")
        self.clear_plot_btn.setProperty("cssClass", "ghost")
        footer.addWidget(self.clear_plot_btn)

        self.export_img_btn = QPushButton("Export Image")
        self.export_img_btn.setProperty("cssClass", "primary")
        footer.addWidget(self.export_img_btn)

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


    def _create_spinbox(self, *, decimals: int, enabled: bool) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(-1_000_000, 1_000_000)
        spin.setEnabled(enabled)
        spin.setProperty("cssClass", "monoInput")
        spin.setMinimumWidth(96)
        spin.setKeyboardTracking(False)
        return spin

    def _build_limit_editor(
        self,
        min_spin: QDoubleSpinBox,
        max_spin: QDoubleSpinBox,
        *,
        unit: str,
    ) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        min_label = QLabel("Min")
        min_label.setProperty("cssClass", "microLabel")
        min_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(min_label)
        layout.addWidget(min_spin)

        max_label = QLabel("Max")
        max_label.setProperty("cssClass", "microLabel")
        max_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(max_label)
        layout.addWidget(max_spin)

        unit_label = QLabel(unit)
        unit_label.setProperty("cssClass", "microLabel")
        unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(unit_label)

        layout.addStretch()
        return container

    def _create_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setProperty("cssClass", "panelDivider")
        return line

    def _add_limit_row(
        self,
        grid: QGridLayout,
        row: int,
        label_text: str,
        widget: QWidget,
        auto_widget: QCheckBox,
    ) -> None:
        label = QLabel(label_text)
        label.setProperty("cssClass", "detailLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setFixedWidth(self._label_width)
        grid.addWidget(label, row, 0)
        grid.addWidget(widget, row, 1)
        grid.addWidget(auto_widget, row, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)

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

        range_text = (
            f"Range:  X  {x_min: .3f}  →  {x_max: .3f}  s    |    "
            f"Y  {y_min: .1f}  →  {y_max: .1f}  mN"
        )
        self.range_label.setText(range_text)

        auto_parts = [
            f"{CHECK_MARK if self.auto_x_cb.isChecked() else CROSS_MARK} X",
            f"{CHECK_MARK if self.auto_y_cb.isChecked() else CROSS_MARK} Y",
        ]
        self.auto_summary_label.setText("Auto:  " + "   ".join(auto_parts))

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
