"""Read-only box state; never present inferred values as confirmed settings."""
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout
from utils.buti_protocol import PROTOCOL_NOTE, RATE_SETUP


class BoxStatusDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Arduino box settings and status")
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        note = QLabel(PROTOCOL_NOTE + "\n\n" + RATE_SETUP)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.reported = QLabel()
        self.reported.setWordWrap(True)
        layout.addWidget(self.reported)
        self.settings = QTableWidget(0, 2)
        self.settings.setHorizontalHeaderLabels(["Last reported setting", "Value"])
        self.settings.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.settings.verticalHeader().hide()
        self.settings.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.settings.setStyleSheet(
            "QTableWidget { background: #454545; color: #ffffff; gridline-color: #666666; }"
            "QHeaderView::section { background: #555555; color: #ffffff; padding: 5px; }"
        )
        layout.addWidget(self.settings)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        def refresh():
            self.status.setText(window._box_observation.description() + ("" if window._device_run_active else " (last run)"))
            self.reported.setText(
                f"Last settings received: {window._buti_settings_received_at}. Changes not reported by the box are unknown."
                if window._buti_settings_received_at else "No experiment settings header received on this connection.")
            labels = {"preload_mm": "Preload (mm)", "deformation_mm": "Deformation (mm)",
                      "deformation_percent": "Deformation (%)", "rate_forward_mm_s": "Forward rate (mm/s)",
                      "rate_reverse_mm_s": "Reverse rate (mm/s)", "wire_diameter_mm": "Wire diameter (mm)",
                      "constant_tension_mn": "Constant tension (mN)"}
            items = list(window._buti_settings.items())
            self.settings.setRowCount(len(items))
            for row, (key, value) in enumerate(items):
                self.settings.setItem(row, 0, QTableWidgetItem(labels.get(key, key.replace("_", " ").capitalize())))
                self.settings.setItem(row, 1, QTableWidgetItem(str(value)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(refresh)
        self.timer.start(500)
        refresh()
