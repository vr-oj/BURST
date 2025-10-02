import logging
import math
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
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

        self._label_width = 132

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

    def set_recording_state(self, recording):
        self.is_recording = recording
        log.debug(f"CameraControlPanel: is_recording set to {self.is_recording}")

    def _setup_float_control(self, prop_id, spinbox, decimals=2, slider=None, to_ui=lambda x: x):
        log.info(f"CameraControlPanel: Looking for property {prop_id}")

        try:
            prop = self.grabber.device_property_map.find_float(prop_id)
            if not prop:
                log.warning(f"CameraControlPanel: Property {prop_id} not found.")
                return 1

            min_val = to_ui(prop.minimum)
            max_val = to_ui(prop.maximum)
            cur_val = to_ui(prop.value)

            # Try to use the property's increment if available; fall back to
            # dividing the range into 100 steps which was the previous
            # behaviour. Using the increment gives a much finer control for
            # properties like ExposureTime that support very small steps.
            step = 0.0
            if hasattr(prop, "has_inc") and callable(getattr(prop, "has_inc")) and prop.has_inc():
                try:
                    step = to_ui(prop.get_inc())
                except Exception:
                    step = None
            else:
                try:
                    step = to_ui(getattr(prop, "increment"))
                except Exception:
                    step = None
            if not step or step <= 0.0:
                step = (max_val - min_val) / 100.0

            spinbox.setRange(min_val, max_val)
            spinbox.setSingleStep(step)

            if step < 1.0:
                # Ensure enough decimal places to represent the step size but
                # avoid artificially increasing the precision. The old formula
                # added one extra decimal place which caused "0.01" steps to
                # display three decimals.
                decimals = max(decimals, int(-math.log10(step)))
            spinbox.setDecimals(min(decimals, 6))

            spinbox.setValue(cur_val)
            spinbox.setEnabled(True)

            scale = 1
            if slider is not None:
                digits = spinbox.decimals()
                scale = 10**digits
                slider.setRange(int(min_val * scale), int(max_val * scale))
                slider.setSingleStep(max(1, int(step * scale)))
                slider.setValue(int(cur_val * scale))
                slider.setEnabled(True)

            log.debug(
                f"{prop_id}: min={min_val}, max={max_val}, step={step}, value={cur_val}, unit={prop.unit}"
            )

            return scale

        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to setup {prop_id}: {e}")

        return 1

    def _on_grabber_ready(self):
        log.info("CameraControlPanel: _on_grabber_ready() called")

        if not self.grabber or not getattr(self.grabber, "is_device_open", False):
            log.error(
                "CameraControlPanel: _on_grabber_ready() called but grabber is not open."
            )
            return

        self._exp_scale = self._setup_float_control(
            "ExposureTime",
            self.exposure_spin,
            decimals=2,
            slider=self.exposure_slider,
            to_ui=lambda v: v / self._exp_unit_factor,
        )
        self._gain_scale = self._setup_float_control(
            "Gain", self.gain_spin, decimals=2, slider=self.gain_slider
        )

        try:
            ae_node = self.grabber.device_property_map.find_enumeration("ExposureAuto")
            self.ae_checkbox.setChecked(ae_node.value == "Continuous")
            self.ae_checkbox.setEnabled(True)
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init ExposureAuto: {e}")

        try:
            ag_node = self.grabber.device_property_map.find_enumeration("GainAuto")
            self.ag_checkbox.setChecked(ag_node.value == "Continuous")
            self.ag_checkbox.setEnabled(True)
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init GainAuto: {e}")

        try:
            # Use the generic helper so missing 'increment' does not disable the control
            self._framerate_scale = self._setup_float_control(
                "AcquisitionFrameRate",
                self.framerate_spin,
                decimals=1,
                slider=self.framerate_slider,
            )
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init AcquisitionFrameRate: {e}")

        try:
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            self.pf_combo.clear()
            for entry in pf_node.entries:
                self.pf_combo.addItem(entry.name)
            current = pf_node.value
            if current:
                idx = self.pf_combo.findText(current)
                if idx >= 0:
                    self.pf_combo.setCurrentIndex(idx)
            self.pf_combo.setEnabled(True)
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init PixelFormat: {e}")

    def _on_exposure_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Exposure change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_float("ExposureTime")
            node.value = float(new_val) * self._exp_unit_factor
            log.debug(f"ExposureTime set to {node.value} µs")
            self.exposure_slider.blockSignals(True)
            self.exposure_slider.setValue(int(float(new_val) * self._exp_scale))
            self.exposure_slider.blockSignals(False)
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set ExposureTime = {new_val}: {e}"
            )

    def _on_gain_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Gain change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_float("Gain")
            node.value = float(new_val)  # ✅ CORRECT
            self.gain_slider.blockSignals(True)
            self.gain_slider.setValue(int(float(new_val) * self._gain_scale))
            self.gain_slider.blockSignals(False)
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set Gain = {new_val}: {e}")

    def _on_auto_exposure_toggled(self, state):
        if self.is_recording:
            log.warning("Blocked Auto Exposure toggle during recording")
            return
        manual_enabled = state != Qt.Checked
        self.exposure_spin.setEnabled(manual_enabled)
        self.exposure_slider.setEnabled(manual_enabled)
        try:
            node = self.grabber.device_property_map.find_enumeration("ExposureAuto")
            node.value = "Continuous" if state == Qt.Checked else "Off"
            self._refresh_auto_values()
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set ExposureAuto: {e}")

    def _on_auto_gain_toggled(self, state):
        if self.is_recording:
            log.warning("Blocked Auto Gain toggle during recording")
            return
        manual_enabled = state != Qt.Checked
        self.gain_spin.setEnabled(manual_enabled)
        self.gain_slider.setEnabled(manual_enabled)
        try:
            node = self.grabber.device_property_map.find_enumeration("GainAuto")
            node.value = "Continuous" if state == Qt.Checked else "Off"
            self._refresh_auto_values()
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set GainAuto: {e}")

    def _on_framerate_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Frame Rate change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_float("AcquisitionFrameRate")
            node.value = float(new_val)  # ✅ FIXED
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set AcquisitionFrameRate = {new_val}: {e}"
            )

    def _on_pf_changed(self, index):
        if self.is_recording:
            log.warning("Blocked Pixel Format change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            new_pf = self.pf_combo.currentText()
            if new_pf:
                node.value = new_pf
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set PixelFormat = {self.pf_combo.currentText()}: {e}"
            )

    def _refresh_auto_values(self):
        if not self.grabber or not getattr(self.grabber, "is_device_open", False):
            return
        if self.ae_checkbox.isChecked():
            try:
                node = self.grabber.device_property_map.find_float("ExposureTime")
                val_ms = node.value / self._exp_unit_factor
                self.exposure_spin.blockSignals(True)
                self.exposure_slider.blockSignals(True)
                self.exposure_spin.setValue(val_ms)
                self.exposure_slider.setValue(int(val_ms * self._exp_scale))
                self.exposure_spin.blockSignals(False)
                self.exposure_slider.blockSignals(False)
            except Exception as e:
                log.debug(f"CameraControlPanel: refresh auto exposure failed: {e}")
        if self.ag_checkbox.isChecked():
            try:
                node = self.grabber.device_property_map.find_float("Gain")
                val = node.value
                self.gain_spin.blockSignals(True)
                self.gain_slider.blockSignals(True)
                self.gain_spin.setValue(val)
                self.gain_slider.setValue(int(val * self._gain_scale))
                self.gain_spin.blockSignals(False)
                self.gain_slider.blockSignals(False)
            except Exception as e:
                log.debug(f"CameraControlPanel: refresh auto gain failed: {e}")
