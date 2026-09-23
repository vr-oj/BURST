"""Acquisition geometry, separate from BURST's saved-image crop."""
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLabel, QSpinBox, QDialogButtonBox


class SensorROIDialog(QDialog):
    def __init__(self, roi, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera sensor region")
        layout = QVBoxLayout(self)
        note = QLabel("Choose the region acquired by the camera, in the adapter's pixel coordinates. "
                      "The camera checks alignment and size limits. This is separate from the recording crop.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.fields = []
        for label, value in zip(("Left", "Top", "Width", "Height"), roi):
            field = QSpinBox()
            # This is the integer input capacity, not a claimed sensor limit.
            field.setRange(1 if label in {"Width", "Height"} else 0, 2147483647)
            field.setValue(value)
            form.addRow(label, field)
            self.fields.append(field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        return ",".join(str(field.value()) for field in self.fields)
