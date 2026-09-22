import logging
import math
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, QSignalBlocker
from PyQt5.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QDoubleSpinBox,
    QCheckBox,
    QComboBox,
    QSlider,
    QSizePolicy,
)
from ..style_constants import PANEL_STYLESHEET

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    def __init__(self, parent=None, *, embedded=False):
        super().__init__(parent)
        self._embedded = bool(embedded)
        self.controller = None
        self.is_recording = False
        self._exp_scale = 1
        self._exp_unit_factor = 1000.0  # property is in µs, display in ms
        self._gain_scale = 1
        self._framerate_scale = 1

        self._auto_update_timer = QTimer(self)
        self._auto_update_timer.setInterval(500)
        self._auto_update_timer.timeout.connect(self._refresh_auto_values)
        self._auto_update_timer.start()

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        panel = QWidget(self) if self._embedded else QFrame(self)
        if not self._embedded:
            panel.setProperty("cssClass", "panelCard")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root_layout.addWidget(panel)

        panel_layout = QVBoxLayout(panel)
        if self._embedded:
            panel_layout.setContentsMargins(0, 0, 0, 0)
        else:
            panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(8)

        if not self._embedded:
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(8)

            title_label = QLabel("Camera Controls")
            title_label.setProperty("cssClass", "panelTitle")
            header_row.addWidget(title_label)
            header_row.addStretch()
            panel_layout.addLayout(header_row)
            panel_layout.addWidget(self._create_divider())

        control_grid = QGridLayout()
        control_grid.setContentsMargins(0, 0, 0, 0)
        control_grid.setVerticalSpacing(8)
        control_grid.setHorizontalSpacing(12)
        control_grid.setColumnStretch(1, 1)
        panel_layout.addLayout(control_grid)

        self._label_width = 96 if self._embedded else 132

        # Exposure
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(2)
        self.exposure_spin.setEnabled(False)
        self.exposure_spin.setProperty("cssClass", "monoInput")
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)

        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setEnabled(False)
        self.exposure_slider.setProperty("cssClass", "controlSlider")
        self.exposure_slider.valueChanged.connect(
            lambda v: self.exposure_spin.setValue(v / self._exp_scale)
        )

        self.ae_checkbox = QCheckBox("Auto")
        self.ae_checkbox.setEnabled(False)
        self.ae_checkbox.setProperty("cssClass", "muted")
        self.ae_checkbox.stateChanged.connect(self._on_auto_exposure_toggled)

        self._add_slider_row(
            control_grid,
            0,
            "Exposure",
            self.exposure_slider,
            self.exposure_spin,
            "ms",
            auto_checkbox=self.ae_checkbox,
        )

        # Gain
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(2)
        self.gain_spin.setEnabled(False)
        self.gain_spin.setProperty("cssClass", "monoInput")
        self.gain_spin.valueChanged.connect(self._on_gain_changed)

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setEnabled(False)
        self.gain_slider.setProperty("cssClass", "controlSlider")
        self.gain_slider.valueChanged.connect(
            lambda v: self.gain_spin.setValue(v / self._gain_scale)
        )

        self.ag_checkbox = QCheckBox("Auto")
        self.ag_checkbox.setEnabled(False)
        self.ag_checkbox.setProperty("cssClass", "muted")
        self.ag_checkbox.stateChanged.connect(self._on_auto_gain_toggled)

        self._add_slider_row(
            control_grid,
            1,
            "Gain",
            self.gain_slider,
            self.gain_spin,
            "dB",
            auto_checkbox=self.ag_checkbox,
        )

        # Frame rate
        self.framerate_spin = QDoubleSpinBox()
        self.framerate_spin.setDecimals(1)
        self.framerate_spin.setEnabled(False)
        self.framerate_spin.setProperty("cssClass", "monoInput")
        self.framerate_spin.valueChanged.connect(self._on_framerate_changed)

        self.framerate_slider = QSlider(Qt.Horizontal)
        self.framerate_slider.setEnabled(False)
        self.framerate_slider.setProperty("cssClass", "controlSlider")
        self.framerate_slider.valueChanged.connect(
            lambda v: self.framerate_spin.setValue(v / self._framerate_scale)
        )

        self._add_slider_row(
            control_grid,
            2,
            "Frame Rate",
            self.framerate_slider,
            self.framerate_spin,
            "fps",
        )

        # Pixel format
        self.pf_combo = QComboBox()
        self.pf_combo.setEnabled(False)
        self.pf_combo.setProperty("cssClass", "monoInput")
        self.pf_combo.currentIndexChanged.connect(self._on_pf_changed)
        self._add_field_row(control_grid, 3, "Pixel Format", self.pf_combo)

        if not self._embedded:
            panel_layout.addStretch()
        self.setStyleSheet(PANEL_STYLESHEET)

    def _create_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setProperty("cssClass", "panelDivider")
        return line

    def _add_slider_row(
        self,
        grid: QGridLayout,
        row: int,
        label_text: str,
        slider: QSlider,
        spinbox: QDoubleSpinBox,
        unit_text: str,
        *,
        auto_checkbox: Optional[QCheckBox] = None,
    ) -> None:
        label = QLabel(label_text)
        label.setProperty("cssClass", "detailLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setFixedWidth(self._label_width)
        grid.addWidget(label, row, 0)

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(slider, 1)

        value_widget = QWidget()
        value_layout = QHBoxLayout(value_widget)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(4)
        value_layout.addWidget(spinbox)

        unit_label = QLabel(unit_text)
        unit_label.setProperty("cssClass", "microLabel")
        unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        value_layout.addWidget(unit_label)

        row_layout.addWidget(value_widget, 0)
        grid.addWidget(row_widget, row, 1)

        if auto_checkbox is not None:
            grid.addWidget(auto_checkbox, row, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        else:
            spacer = QWidget()
            spacer.setFixedWidth(1)
            grid.addWidget(spacer, row, 2)

    def _add_field_row(self, grid: QGridLayout, row: int, label_text: str, widget: QWidget) -> None:
        label = QLabel(label_text)
        label.setProperty("cssClass", "detailLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setFixedWidth(self._label_width)
        grid.addWidget(label, row, 0)
        grid.addWidget(widget, row, 1)
        spacer = QWidget()
        spacer.setFixedWidth(1)
        grid.addWidget(spacer, row, 2)

    def stop_auto_update(self):
        """Stop polling camera properties."""
        self._auto_update_timer.stop()

    def start_auto_update(self):
        """Start polling camera properties if not already active."""
        if not self._auto_update_timer.isActive():
            self._auto_update_timer.start()

    def set_controller(self, controller):
        self.controller = controller
        self._refresh_auto_values()
        if controller is not None:
            self.start_auto_update()
        else:
            self.stop_auto_update()

    def set_recording_state(self, recording):
        self.is_recording = bool(recording)
        self._refresh_auto_values()

    def _refresh_auto_values(self):
        capabilities = self.controller.capabilities() if self.controller else {}
        self.setToolTip(self.controller.last_error if self.controller else "")
        rows = (
            ("exposure", self.exposure_spin, self.exposure_slider, "_exp_scale", 1000.0, "auto_exposure"),
            ("gain", self.gain_spin, self.gain_slider, "_gain_scale", 1.0, "auto_gain"),
            ("fps", self.framerate_spin, self.framerate_slider, "_framerate_scale", 1.0, None),
        )
        for name, spin, slider, scale_name, factor, auto_name in rows:
            prop = capabilities.get(name)
            auto = capabilities.get(auto_name)
            enabled = bool(prop and prop.writable and not self.is_recording
                           and not (auto and auto.value != "Off"))
            spin.setEnabled(enabled)
            slider.setEnabled(enabled)
            if prop is None or spin.hasFocus() or slider.isSliderDown():
                continue
            lo, hi, value = prop.minimum / factor, prop.maximum / factor, float(prop.value) / factor
            if not all(math.isfinite(v) for v in (lo, hi, value)) or hi < lo:
                spin.setEnabled(False)
                slider.setEnabled(False)
                continue
            step = prop.increment / factor or max((hi - lo) / 100, 0.001)
            blockers = [QSignalBlocker(spin), QSignalBlocker(slider)]
            if 0 < step < 1:
                spin.setDecimals(min(6, max(spin.decimals(), math.ceil(-math.log10(step)))))
            # QSlider uses signed 32-bit integers even for cameras with huge ranges.
            scale = min(10 ** spin.decimals(), (2**30) / max(abs(lo), abs(hi), 1))
            setattr(self, scale_name, scale)
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setValue(value)
            slider.setRange(int(lo * scale), int(hi * scale))
            slider.setSingleStep(max(1, int(step * scale)))
            slider.setValue(int(value * scale))
            del blockers
        for name, checkbox in (("auto_exposure", self.ae_checkbox), ("auto_gain", self.ag_checkbox)):
            prop = capabilities.get(name)
            blocker = QSignalBlocker(checkbox)
            checkbox.setChecked(bool(prop and prop.value != "Off"))
            checkbox.setEnabled(bool(prop and prop.writable and not self.is_recording
                                     and {"Off", "Continuous"}.issubset(prop.choices)))
            del blocker
        prop = capabilities.get("pixel_format")
        blocker = QSignalBlocker(self.pf_combo)
        choices = list(prop.choices) if prop else []
        if choices != [self.pf_combo.itemText(i) for i in range(self.pf_combo.count())]:
            self.pf_combo.clear()
            self.pf_combo.addItems(choices)
        if prop:
            self.pf_combo.setCurrentText(str(prop.value))
        self.pf_combo.setEnabled(bool(prop and prop.writable and not self.is_recording))
        del blocker

    def _set_value(self, name, value):
        if self.controller is not None and not self.is_recording:
            self.controller.set_value(name, value)

    def _on_exposure_changed(self, value):
        self._set_value("exposure", float(value) * self._exp_unit_factor)

    def _on_gain_changed(self, value):
        self._set_value("gain", float(value))

    def _on_framerate_changed(self, value):
        self._set_value("fps", float(value))

    def _on_auto_exposure_toggled(self, state):
        self._set_value("auto_exposure", "Continuous" if state == Qt.Checked else "Off")

    def _on_auto_gain_toggled(self, state):
        self._set_value("auto_gain", "Continuous" if state == Qt.Checked else "Off")

    def _on_pf_changed(self, index):
        if index >= 0:
            self._set_value("pixel_format", self.pf_combo.currentText())
