"""User-owned Micro-Manager configurations; native work stays off the GUI thread."""
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QListWidget, QDialogButtonBox)
from cameras.micro_manager_backend import MicroManagerSession, validate_profile, installation_candidates


class ConfigurationProbe(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, sdk, profile, parent=None):
        super().__init__(parent)
        self.sdk, self.profile = sdk, profile

    def run(self):
        try:
            with MicroManagerSession(self.sdk, self.profile) as session:
                cameras = list(session.core.getLoadedDevicesOfType(self.sdk.CameraDevice))
                details = {"cameras": cameras, "selected": session.camera,
                           "version": session.core.getVersionInfo(), "api": session.core.getAPIVersionInfo()}
            self.result.emit(details)
        except Exception as exc:
            self.failed.emit(str(exc))


class MicroManagerSetupDialog(QDialog):
    def __init__(self, sdk, profiles=(), parent=None, unavailable=""):
        super().__init__(parent)
        self.sdk = sdk
        self.profiles = [dict(p) for p in profiles if isinstance(p, dict)]
        self.worker = None
        self.validated = None
        self.setWindowTitle("Micro-Manager Camera Setup")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        intro = QLabel("Select your Micro-Manager installation and saved hardware configuration. "
            "Keep vendor drivers installed and close Micro-Manager before connecting here. "
            "Use a camera-only configuration where possible: loading a configuration initializes all devices it contains. "
            "BURST remembers the file location; keep the configuration in a permanent folder.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(QLabel("Saved cameras"))
        self.saved = QListWidget()
        self.saved.setStyleSheet("QListWidget { background: #2d2d2d; color: #f0f0f0; }")
        layout.addWidget(self.saved)
        remove = QPushButton("Remove selected saved camera")
        remove.clicked.connect(self._remove)
        layout.addWidget(remove)
        self.installation = QLineEdit()
        candidates = installation_candidates()
        if candidates:
            self.installation.setText(candidates[-1])
        self.config = QLineEdit()
        for title, field, callback in (("Micro-Manager folder", self.installation, self._browse_installation),
                                      ("Hardware configuration (.cfg)", self.config, self._browse_config)):
            layout.addWidget(QLabel(title))
            row = QHBoxLayout()
            row.addWidget(field)
            browse = QPushButton("Browse…")
            browse.clicked.connect(callback)
            row.addWidget(browse)
            layout.addLayout(row)
            field.textChanged.connect(self._invalidate)
        self.test = QPushButton("Load configuration and find cameras")
        self.test.clicked.connect(self._probe)
        layout.addWidget(self.test)
        self.cameras = QComboBox()
        layout.addWidget(self.cameras)
        self.add = QPushButton("Add selected camera")
        self.add.setEnabled(False)
        self.add.clicked.connect(self._add)
        layout.addWidget(self.add)
        self.status = QLabel("No configuration loaded yet. Camera capture is checked when you start its preview.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh_saved()
        if sdk is None:
            self.test.setEnabled(False)
            self.status.setText("This BURST installation cannot load Micro-Manager support. "
                "Install a BURST release with Micro-Manager support, then use matching Micro-Manager device adapters. "
                + unavailable)

    def _refresh_saved(self):
        self.saved.clear()
        for p in self.profiles:
            self.saved.addItem(f"{p.get('camera', '?')} — {p.get('config', '')}")

    def _remove(self):
        index = self.saved.currentRow()
        if index >= 0:
            self.profiles.pop(index)
            self._refresh_saved()

    def _browse_installation(self):
        if self.worker is not None:
            return
        path = QFileDialog.getExistingDirectory(self, "Micro-Manager installation", self.installation.text())
        if path:
            self.installation.setText(path)

    def _browse_config(self):
        if self.worker is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Micro-Manager configuration", self.config.text(), "Hardware configurations (*.cfg)")
        if path:
            self.config.setText(path)

    def _invalidate(self):
        self.validated = None
        self.cameras.clear()
        self.add.setEnabled(False)

    def _probe(self):
        if self.worker is not None:
            return
        try:
            profile = validate_profile({"installation": self.installation.text(), "config": self.config.text()})
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._invalidate()
        self._pending_profile = profile
        self.test.setEnabled(False)
        self.installation.setReadOnly(True)
        self.config.setReadOnly(True)
        self.buttons.setEnabled(False)
        self.status.setText("Loading configuration… Waiting for the camera driver. This may take a few seconds.")
        self.worker = ConfigurationProbe(self.sdk, profile, self)
        self.worker.result.connect(self._loaded)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _loaded(self, details):
        self.validated = dict(self._pending_profile)
        self.cameras.addItems(details["cameras"])
        self.cameras.setCurrentText(details["selected"])
        self.status.setText(f"Configuration loaded. {details['version']}; {details['api']}. "
            "Choose a camera and add it. Image delivery and synchronization have not been verified.")

    def _failed(self, message):
        self.validated = None
        self.cameras.clear()
        self.status.setText("Could not load the configuration: " + message +
            "\nCheck vendor drivers, close other camera applications, and use device adapters compatible with BURST's MMCore. "
            "An older Micro-Manager installation may need updating.")

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.test.setEnabled(self.sdk is not None)
        self.installation.setReadOnly(False)
        self.config.setReadOnly(False)
        self.buttons.setEnabled(True)
        self.add.setEnabled(self.validated is not None)

    def _add(self):
        if self.validated is None or not self.cameras.currentText():
            return
        profile = dict(self.validated, camera=self.cameras.currentText())
        if profile not in self.profiles:
            self.profiles.append(profile)
            self._refresh_saved()
        self.status.setText("Camera added. Save, select it in Camera Device, and start the preview.")

    def accept(self):
        if self.worker is None:
            super().accept()

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)
