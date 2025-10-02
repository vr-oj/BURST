# File: buti_app/ui/welcome_dialog.py

import os
import sys
import subprocess
from utils.path_helpers import resource_path
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QWidget,
    QLabel,
    QPushButton,
    QCheckBox,
    QDesktopWidget,
)


class WelcomeDialog(QDialog):
    """Simple welcome screen shown on first launch"""

    def __init__(self, parent=None, force_show: bool = False):
        super().__init__(parent)

        # Persistent setting
        self.settings = QSettings("YourCompany", "BURSTApp")
        self._skip = False
        if not force_show:
            show_welcome = self.settings.value("BURSTApp/ShowWelcome", None, type=bool)
            if show_welcome is None:
                legacy_settings = QSettings("YourCompany", "BUTIApp")
                show_welcome = legacy_settings.value("BUTIApp/ShowWelcome", True, type=bool)
                self.settings.setValue("BURSTApp/ShowWelcome", show_welcome)
            if not show_welcome:
                self._skip = True
                self.close()
                return

        self.setWindowTitle("Welcome to BURST")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(500, 420)
        self.setStyleSheet(
            """
            QDialog { background-color: #2b2b2b; color: white; border-radius: 10px; }
            QLabel { font-size: 10pt; }
            QPushButton { background-color: #3a7bd5; color: white; border-radius: 5px; padding: 6px 12px; }
            QPushButton:hover { background-color: #559de8; }
            """
        )

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(16, 16, 16, 16)

        intro = QLabel(
            "BURST (BUTI Uniaxial Recording of Strain &amp; Tension) pairs the BUTI Arduino Box with your camera to record synchronized <b>force-vs-time data and video</b> for your experiments.<br>"
            "Follow these steps to get started quickly:"
        )
        main_layout.addWidget(intro)

        steps = [
            ("plug.svg", "Connect BUTI Arduino Box", "Select the BUTI Arduino Box COM port and click Connect"),
            ("camera.svg", "Set Up Camera", "Choose camera & resolution then click Start Camera"),
            ("settings.svg", "Adjust Exposure/Gain", "Use controls to fine-tune camera settings"),
            ("sync.svg", "Zero BURST", "Make sure force is zero"),
            ("record.svg", "Start Recording", "Click Start Recording to begin acquisition"),
            ("stop.svg", "Stop Recording", "Click Stop Recording when finished"),
            ("export.svg", "Playback & Export", "Click Playback to review and export frames"),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setAlignment(Qt.AlignTop)

        for i, (icon, title, desc) in enumerate(steps, start=1):
            step_widget = QWidget()
            step_layout = QVBoxLayout(step_widget)
            step_layout.setSpacing(4)
            step_layout.setAlignment(Qt.AlignTop)

            top_row = QHBoxLayout()
            top_row.setSpacing(6)


            icon_lbl = QLabel()
            icon_path = resource_path("ui", "icons", icon)
            icon_lbl.setPixmap(
                QPixmap(icon_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

            icon_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            title_lbl = QLabel(f"{i}. {title}")
            title_lbl.setStyleSheet("font-size: 11pt; font-weight: bold;")
            title_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            top_row.addWidget(icon_lbl)
            top_row.addWidget(title_lbl)
            top_row.addStretch()

            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("font-size: 9pt; color: #aaaaaa;")
            desc_lbl.setAlignment(Qt.AlignLeft)

            step_layout.addLayout(top_row)
            step_layout.addWidget(desc_lbl)

            row = (i - 1) // 2
            col = (i - 1) % 2
            grid.addWidget(step_widget, row, col)

        main_layout.addLayout(grid)


        self.checkbox = QCheckBox("Don't show this again")
        self.checkbox.stateChanged.connect(self._toggle_show)
        main_layout.addWidget(self.checkbox)

        footer = QHBoxLayout()
        readme_btn = QPushButton("Read Full User Guide →")
        readme_btn.clicked.connect(self._open_user_guide)
        footer.addWidget(readme_btn)
        footer.addStretch()
        start_btn = QPushButton("Start Using BURST")
        start_btn.clicked.connect(self.accept)
        footer.addWidget(start_btn)
        main_layout.addLayout(footer)

        qr = self.frameGeometry()
        cp = QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def _toggle_show(self, state):
        self.settings.setValue("BURSTApp/ShowWelcome", state != Qt.Checked)
        legacy_settings = QSettings("YourCompany", "BUTIApp")
        legacy_settings.setValue("BUTIApp/ShowWelcome", state != Qt.Checked)

    def _open_user_guide(self):
        # Use resource_path so PyInstaller builds can locate the PDF
        pdf_path = resource_path("docs", "BURST_UserGuide.pdf")
        if os.path.exists(pdf_path):
            if sys.platform == "win32":
                os.startfile(pdf_path)
            elif sys.platform == "darwin":
                subprocess.call(["open", pdf_path])
            else:
                subprocess.call(["xdg-open", pdf_path])
