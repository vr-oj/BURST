from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, QLineEdit,
                            QPushButton, QDialogButtonBox)


class CameraPropertiesDialog(QDialog):
    """Native property names/units with worker-owned writes and readback."""
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.controller = panel.controller
        self.setWindowTitle("Micro-Manager Camera Properties")
        self.resize(590, 360)
        layout = QVBoxLayout(self)
        note = QLabel("These are the controls exposed by your camera's Micro-Manager adapter, in its native units. "
            "Changes briefly restart the preview and apply to this camera session only. "
            "Save permanent settings in your Micro-Manager configuration. Trigger settings alone do not verify synchronization.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.names = QComboBox()
        for name in self.controller.capabilities():
            if name.startswith(("mm:", "mmcore:")):
                self.names.addItem(name.split(":", 1)[1], name)
        layout.addWidget(self.names)
        self.current = QLabel()
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        self.choices = QComboBox()
        self.value = QLineEdit()
        layout.addWidget(self.choices)
        layout.addWidget(self.value)
        self.apply = QPushButton("Apply to camera")
        self.apply.clicked.connect(self._apply)
        layout.addWidget(self.apply)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.names.currentIndexChanged.connect(self._selected)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()
        self._selected()

    def _selected(self):
        prop = self.controller.capabilities().get(self.names.currentData())
        self.choices.clear()
        if prop:
            self.choices.addItems(prop.choices)
            self.choices.setCurrentText(str(prop.value))
            self.value.setText(str(prop.value))
        self.choices.setVisible(bool(prop and prop.choices))
        self.value.setVisible(not bool(prop and prop.choices))
        self._refresh()

    def _refresh(self):
        prop = self.controller.capabilities().get(self.names.currentData())
        enabled = bool(prop and prop.writable and not self.panel.is_recording
                       and self.panel.controller is self.controller)
        self.apply.setEnabled(enabled)
        self.value.setEnabled(enabled)
        self.choices.setEnabled(enabled)
        if prop:
            limits = f" · Range: {prop.minimum:g}–{prop.maximum:g}" if prop.maximum > prop.minimum else ""
            self.current.setText(f"Camera readback: {prop.value}{limits}" + (" · Read-only / setup-only" if not prop.writable else ""))
        else:
            self.current.setText("Camera is disconnected.")
        if self.controller.last_error:
            self.message.setText(self.controller.last_error)

    def _apply(self):
        if not self.apply.isEnabled():
            return
        value = self.choices.currentText() if self.choices.isVisible() else self.value.text()
        self.panel._set_value(self.names.currentData(), value)
        self.message.setText("Change requested. Check camera readback above for the applied value.")
