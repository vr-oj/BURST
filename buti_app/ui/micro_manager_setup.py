"""User-owned Micro-Manager configurations; native work stays off the GUI thread."""
from copy import deepcopy
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QListWidget, QDialogButtonBox, QTextEdit, QSizePolicy)
import logging
from cameras.micro_manager_backend import validate_profile, installation_candidates
from cameras.micro_manager_process import MicroManagerClient, MicroManagerCancelled
from cameras.micro_manager_discovery import find_cameras
from cameras.micro_manager_profiles import profile_key, read_profile, write_profile

log = logging.getLogger(__name__)


class ConfigurationProbe(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, sdk, profile, parent=None):
        super().__init__(parent)
        self.sdk, self.profile = sdk, profile

    def run(self):
        try:
            log.info("Loading Micro-Manager configuration in isolated helper: %s (adapters: %s)",
                     self.profile.get("config", self.profile.get("connection")), self.profile["installation"])
            with MicroManagerClient(cancelled=self.isInterruptionRequested) as client:
                details = client.request("probe", self.profile)
            log.info("Micro-Manager configuration loaded: %s", details)
            self.result.emit(details)
        except MicroManagerCancelled:
            pass
        except Exception as exc:
            log.exception("Micro-Manager configuration probe failed")
            self.failed.emit(str(exc))


class CameraSearch(QThread):
    result = pyqtSignal(object)
    progress = pyqtSignal(str)

    def __init__(self, installations, parent=None):
        super().__init__(parent)
        self.installations = installations

    def run(self):
        self.result.emit(find_cameras(self.installations, MicroManagerClient,
            cancelled=self.isInterruptionRequested, progress=self.progress.emit))


class MicroManagerSetupDialog(QDialog):
    def __init__(self, sdk, profiles=(), parent=None, unavailable=""):
        super().__init__(parent)
        self.sdk = sdk
        self.profiles = [deepcopy(p) for p in profiles if isinstance(p, dict)]
        self._controls = {}
        self._imported = None
        self._mapping_index = None
        self.worker = None
        self._cancel_requested = False
        self.validated = None
        self.setWindowTitle("Micro-Manager Camera Setup")
        self.resize(760, 720)
        layout = QVBoxLayout(self)
        intro = QLabel("Find cameras using installed Micro-Manager adapters, or load a saved hardware configuration. "
            "Keep vendor drivers installed and close other camera applications first. "
            "Use a camera-only configuration: importing a configuration initializes every device in it.")
        intro.setWordWrap(True)
        intro.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout.addWidget(intro)
        layout.addWidget(QLabel("Saved cameras"))
        self.saved = QListWidget()
        self.saved.setStyleSheet("QListWidget { background: #2d2d2d; color: #f0f0f0; }")
        layout.addWidget(self.saved)
        remove = QPushButton("Remove selected saved camera")
        remove.clicked.connect(self._remove)
        saved_actions = QHBoxLayout()
        saved_actions.addWidget(remove)
        self.mapping = QPushButton("Advanced camera mapping…")
        self.mapping.clicked.connect(self._map_saved)
        saved_actions.addWidget(self.mapping)
        layout.addLayout(saved_actions)
        sharing = QHBoxLayout()
        for title, callback in (("Import camera profile…", self._import), ("Export selected profile…", self._export)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            sharing.addWidget(button)
        layout.addLayout(sharing)
        self.installation = QLineEdit()
        candidates = installation_candidates()
        previous = next((p["installation"] for p in reversed(self.profiles)
                         if Path(p.get("installation", "")).is_dir() and p.get("installation")), None)
        if previous or candidates:
            self.installation.setText(previous or candidates[-1])
        self.config = QLineEdit()
        for title, field, callback in (("Micro-Manager folder", self.installation, self._browse_installation),
                                      ("Hardware configuration (.cfg, optional)", self.config, self._browse_config)):
            if field is self.config:
                find_position = layout.count()
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
        row = QHBoxLayout()
        self.find = QPushButton("Find cameras")
        self.find.clicked.connect(self._find)
        row.addWidget(self.find)
        self.cancel_search = QPushButton("Cancel search")
        self.cancel_search.setVisible(False)
        self.cancel_search.clicked.connect(self._cancel_search)
        row.addWidget(self.cancel_search)
        layout.insertLayout(find_position, row)
        self.cameras = QComboBox()
        layout.addWidget(self.cameras)
        self.add = QPushButton("Add selected camera")
        self.add.setEnabled(False)
        self.add.clicked.connect(self._add)
        layout.addWidget(self.add)
        self.status = QLabel("No configuration loaded yet. Camera capture is checked when you start its preview.")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout.addWidget(self.status)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(100)
        self.details.hide()
        layout.addWidget(self.details)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh_saved()
        if sdk is None:
            self.test.setEnabled(False)
            self.find.setEnabled(False)
            self.mapping.setEnabled(False)
            self.status.setText("This BURST installation cannot load Micro-Manager support. "
                "Install a BURST release with Micro-Manager support, then use matching Micro-Manager device adapters. "
                + unavailable)

    def _refresh_saved(self):
        self.saved.clear()
        for p in self.profiles:
            self.saved.addItem(f"{p.get('display_name', p.get('camera', '?'))} — "
                              f"{p.get('connection', {}).get('library') or p.get('config', '')}")

    def _remove(self):
        if self.worker is not None:
            return
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
            log.info("Selected Micro-Manager configuration: %s", path)
            self.config.setText(path)

    def _invalidate(self):
        self.validated = None
        self.cameras.clear()
        self.add.setEnabled(False)

    def _probe(self):
        if self.worker is not None:
            return
        try:
            profile = dict(self._imported or {}, installation=self.installation.text())
            if not profile.get("connection"):
                profile["config"] = self.config.text()
            profile = validate_profile(profile)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._begin_probe(profile)

    def _begin_probe(self, profile, mapping=False):
        self._invalidate()
        self._pending_profile = profile
        # Read native properties even when a previously saved mapping has gone stale.
        probe = dict(profile, bindings={}, timing={}) if mapping else profile
        worker = ConfigurationProbe(self.sdk, probe, self)
        worker.result.connect(self._mapping_loaded if mapping else self._loaded)
        worker.failed.connect(self._failed)
        self._start_worker(worker, "Loading camera configuration…")

    def _start_worker(self, worker, message):
        self._cancel_requested = False
        self.test.setEnabled(False)
        self.find.setEnabled(False)
        self.mapping.setEnabled(False)
        self.installation.setReadOnly(True)
        self.config.setReadOnly(True)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.status.setText(message)
        self.details.hide()
        self.worker = worker
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _find(self):
        if self.worker is not None:
            return
        self._imported = None
        self._invalidate()
        installations = [self.installation.text(), *installation_candidates()]
        worker = CameraSearch([p for p in installations if p], self)
        worker.result.connect(self._found)
        worker.progress.connect(self.status.setText)
        self.cancel_search.setVisible(True)
        self._start_worker(worker, "Finding cameras… Up to 10 seconds per adapter, 60 seconds total.")

    def _cancel_search(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.status.setText("Cancelling search; keeping cameras already found…")

    def _found(self, details):
        for result in details["cameras"]:
            profile = result["profile"]
            self.cameras.addItem(profile.get("display_name", profile["camera"]), profile)
            self._controls[profile_key(profile)] = result["controls"]
        self.validated = {} if details["cameras"] else None
        self.status.setText(f"Found {len(details['cameras'])} camera(s). Choose a camera and add it. "
                           "If yours is missing, load its Micro-Manager configuration above.")
        self.details.setPlainText("\n".join(details["issues"]))
        self.details.setVisible(bool(details["issues"]))

    def _loaded(self, details):
        self.validated = dict(self._pending_profile)
        self._configured_modes = details.get("modes", {})
        self.cameras.addItems(details["cameras"])
        self.cameras.setCurrentText(details["selected"])
        for camera, controls in details.get("controls", {}).items():
            self._controls[profile_key(dict(self.validated, camera=camera))] = controls
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
        self.find.setEnabled(self.sdk is not None)
        self.mapping.setEnabled(self.sdk is not None)
        self.cancel_search.hide()
        self.installation.setReadOnly(False)
        self.config.setReadOnly(False)
        self.buttons.setEnabled(True)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
        self.add.setEnabled(self.validated is not None)
        if self._cancel_requested:
            super().reject()

    def _add(self):
        if self.validated is None or not self.cameras.currentText():
            return
        profile = self.cameras.currentData() or dict(self.validated, camera=self.cameras.currentText())
        mode = getattr(self, "_configured_modes", {}).get(profile["camera"]) if self.cameras.currentData() is None else None
        if mode:
            profile["configured_mode"] = mode
        old = next((p for p in self.profiles if profile_key(p) == profile_key(profile)), None)
        if old and not self._imported:
            profile = dict(profile, bindings=old.get("bindings", {}), timing=old.get("timing", {}))
        self.profiles = [p for p in self.profiles if profile_key(p) != profile_key(profile)]
        self.profiles.append(deepcopy(profile))
        self._refresh_saved()
        self.saved.setCurrentRow(len(self.profiles) - 1)
        self.status.setText("Camera added. Save, select it in Camera Device, and start the preview.")

    def _map_saved(self):
        index = self.saved.currentRow()
        if self.worker is not None:
            return
        if self._imported is not None:
            profile = dict(self._imported, installation=self.installation.text())
            if not profile.get("connection"):
                profile["config"] = self.config.text()
            self._mapping_index = None
            self._begin_probe(profile, mapping=True)
            return
        if index < 0:
            self.status.setText("Select a saved camera to edit its mapping.")
            return
        self._mapping_index = index
        self._begin_probe(self.profiles[index], mapping=True)

    def _mapping_loaded(self, details):
        from ui.micro_manager_mapping import MicroManagerMappingDialog
        profile = self._pending_profile
        profile = dict(profile, camera=profile.get("camera") or details["selected"])
        controls = details.get("controls", {}).get(profile["camera"], {})
        dialog = MicroManagerMappingDialog(profile, controls, self)
        if dialog.exec_() == QDialog.Accepted:
            if self._mapping_index is None:
                self._imported = dialog.profile
            else:
                self.profiles[self._mapping_index] = dialog.profile
            self._refresh_saved()
            self.status.setText("Mapping saved for this camera. BURST will validate it again when connecting.")

    def _import(self):
        if self.worker is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import camera profile", "", "Camera profiles (*.json)")
        if not path:
            return
        try:
            profile = read_profile(path)
            if not Path(profile["installation"]).is_dir():
                profile["installation"] = self.installation.text()
            self.installation.setText(profile["installation"])
            self.config.setText(profile.get("config", ""))
            self._imported = profile
            self.status.setText("Profile imported. Check local installation/configuration paths, then Load configuration and find cameras.")
        except (ValueError, OSError) as exc:
            self.status.setText("Could not import camera profile: " + str(exc))

    def _export(self):
        index = self.saved.currentRow()
        if self.worker is not None or index < 0:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export camera profile", "camera-profile.json", "Camera profiles (*.json)")
        if path:
            try:
                write_profile(path, self.profiles[index])
                self.status.setText("Profile exported. The receiving lab must install its adapters/drivers and select local paths.")
            except (ValueError, OSError) as exc:
                self.status.setText("Could not export camera profile: " + str(exc))

    def accept(self):
        if self.worker is None:
            super().accept()

    def reject(self):
        if self.worker is None:
            super().reject()
        else:
            self._cancel_requested = True
            self.worker.requestInterruption()
            self.status.setText("Cancelling camera setup and closing its helper…")

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
