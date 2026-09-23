"""User-owned Micro-Manager configurations; native work stays off the GUI thread."""
from copy import deepcopy
from pathlib import Path
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QListWidget, QDialogButtonBox, QTextEdit, QSizePolicy,
    QWidget, QToolButton)
import logging
from cameras.micro_manager_backend import validate_profile, installation_candidates
from cameras.micro_manager_process import MicroManagerClient, MicroManagerCancelled
from cameras.micro_manager_discovery import find_cameras
from cameras.micro_manager_profiles import profile_key, read_profile, write_profile
from ui.style_constants import PANEL_STYLESHEET

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
        self.setMinimumWidth(640)
        self.resize(680, 490)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        intro = QLabel("Add a camera through Micro-Manager. IC4 cameras connect directly "
                       "and do not need this setup.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        prerequisite = QLabel("Install your camera's drivers and close other camera applications first.")
        prerequisite.setWordWrap(True)
        prerequisite.setProperty("cssClass", "detailLabel")
        layout.addWidget(prerequisite)

        self.installation = QLineEdit()
        candidates = installation_candidates()
        previous = next((p["installation"] for p in reversed(self.profiles)
                         if Path(p.get("installation", "")).is_dir() and p.get("installation")), None)
        if previous or candidates:
            self.installation.setText(previous or candidates[-1])
        self.config = QLineEdit()
        installation_row = QHBoxLayout()
        self.installation_summary = QLabel()
        self.installation_summary.setWordWrap(True)
        installation_row.addWidget(self.installation_summary, 1)
        self.change_folder = QPushButton("Change folder…")
        self.change_folder.clicked.connect(self._browse_installation)
        installation_row.addWidget(self.change_folder)
        layout.addLayout(installation_row)

        search_row = QHBoxLayout()
        self.find = QPushButton("Find cameras")
        self.find.setProperty("cssClass", "primary")
        self.find.setDefault(True)
        self.find.clicked.connect(self._find)
        search_row.addWidget(self.find)
        self.load_config = QPushButton("Load configuration…")
        self.load_config.clicked.connect(self._browse_config)
        self.load_config.setToolTip("Choose a camera-only Micro-Manager .cfg file. "
                                   "Loading a configuration initializes every device listed in it.")
        search_row.addWidget(self.load_config)
        search_row.addStretch()
        self.cancel_search = QPushButton("Cancel search")
        self.cancel_search.hide()
        self.cancel_search.clicked.connect(self._cancel_search)
        search_row.addWidget(self.cancel_search)
        layout.addLayout(search_row)

        status_row = QHBoxLayout()
        self.status = QLabel("Find a connected camera, or load a configuration you already use.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        status_row.addWidget(self.status, 1)
        self.details_button = QPushButton("Details…")
        self.details_button.clicked.connect(self._show_details)
        self.details_button.hide()
        status_row.addWidget(self.details_button)
        layout.addLayout(status_row)
        # Keep diagnostics available without expanding the normal setup flow.
        self.details = QTextEdit(self)
        self.details.hide()
        self.details.setReadOnly(True)

        results_row = QHBoxLayout()
        results_row.addWidget(QLabel("Camera"))
        self.cameras = QComboBox()
        self.cameras.setMinimumWidth(0)
        self.cameras.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cameras.setPlaceholderText("Available cameras")
        self.cameras.setEnabled(False)
        results_row.addWidget(self.cameras, 1)
        self.add = QPushButton("Add camera")
        self.add.setEnabled(False)
        self.add.clicked.connect(self._add)
        results_row.addWidget(self.add)
        layout.addLayout(results_row)

        saved_header = QHBoxLayout()
        saved_header.addWidget(QLabel("Saved cameras"))
        saved_header.addStretch()
        self.remove = QPushButton("Remove")
        self.remove.clicked.connect(self._remove)
        saved_header.addWidget(self.remove)
        layout.addLayout(saved_header)
        self.saved = QListWidget()
        self.saved.setMinimumHeight(80)
        self.saved.setMaximumHeight(125)
        self.saved.setStyleSheet("QListWidget { background: #2d2d2d; color: #f0f0f0; }")
        self.saved.currentRowChanged.connect(self._update_actions)
        layout.addWidget(self.saved)
        saved_hint = QLabel("After saving, choose your camera from BURST's Camera Device list.")
        saved_hint.setWordWrap(True)
        saved_hint.setProperty("cssClass", "detailLabel")
        layout.addWidget(saved_hint)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced options")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setStyleSheet(
            "QToolButton { color: #e0e0e0; background: transparent; border: none; padding: 4px 0; }"
            "QToolButton:hover { color: white; }")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        for title, field in (("Micro-Manager folder", self.installation),
                             ("Configuration file (.cfg)", self.config)):
            advanced_layout.addWidget(QLabel(title))
            advanced_layout.addWidget(field)
            field.textChanged.connect(self._invalidate)
        self.installation.textChanged.connect(self._update_installation_summary)
        self.test = QPushButton("Check configuration")
        self.test.clicked.connect(self._probe)
        advanced_layout.addWidget(self.test)
        sharing = QHBoxLayout()
        self.mapping = QPushButton("Advanced camera mapping…")
        self.mapping.clicked.connect(self._map_saved)
        sharing.addWidget(self.mapping)
        self.import_button = QPushButton("Import profile…")
        self.import_button.clicked.connect(self._import)
        sharing.addWidget(self.import_button)
        self.export_button = QPushButton("Export profile…")
        self.export_button.clicked.connect(self._export)
        sharing.addWidget(self.export_button)
        advanced_layout.addLayout(sharing)
        layout.addWidget(self.advanced)
        self.advanced.hide()

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setStyleSheet(PANEL_STYLESHEET)
        self._update_installation_summary()
        self._refresh_saved()
        self._update_actions()
        if sdk is None:
            self.status.setText("Micro-Manager support is missing from this BURST installation. "
                                "Install a BURST build with Micro-Manager support.")
            self._set_details(unavailable)

    def _update_installation_summary(self):
        folder = self.installation.text()
        self.installation_summary.setText("Micro-Manager: " + Path(folder).name if folder else
                                          "Micro-Manager not found. Choose its installation folder.")
        self.installation_summary.setToolTip(folder)

    def _update_actions(self):
        idle = self.worker is None
        available = idle and self.sdk is not None
        selected = self.saved.currentRow() >= 0
        self.find.setEnabled(available)
        self.load_config.setEnabled(available)
        self.test.setEnabled(available)
        self.change_folder.setEnabled(idle)
        self.remove.setEnabled(idle and selected)
        self.mapping.setEnabled(available and (selected or self._imported is not None))
        self.import_button.setEnabled(idle)
        self.export_button.setEnabled(idle and selected)
        self.cameras.setEnabled(idle and self.cameras.count() > 0)
        self.add.setEnabled(idle and self.validated is not None and self.cameras.currentIndex() >= 0)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(idle)

    def _toggle_advanced(self, expanded):
        width = self.width()
        self.advanced.setVisible(expanded)
        self.advanced_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.adjustSize()
        self.resize(width, self.height())

    def _set_details(self, text):
        self.details.setPlainText(text)
        self.details_button.setVisible(bool(text))

    def _show_details(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Camera setup details")
        dialog.resize(640, 360)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self.details.toPlainText())
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()

    def _refresh_saved(self):
        selected = self.saved.currentRow()
        self.saved.clear()
        for p in self.profiles:
            name = p.get("display_name") or p.get("camera", "Camera")
            if not p.get("display_name") and p.get("config"):
                name = f"{Path(p['config']).stem} · {name}"
            self.saved.addItem(name)
            self.saved.item(self.saved.count() - 1).setToolTip(
                p.get("connection", {}).get("library") or p.get("config", ""))
        if self.profiles:
            self.saved.setCurrentRow(max(0, min(selected, len(self.profiles) - 1)))

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
        path, _ = QFileDialog.getOpenFileName(self, "Choose a camera-only Micro-Manager configuration", self.config.text(), "Hardware configurations (*.cfg)")
        if path:
            log.info("Selected Micro-Manager configuration: %s", path)
            self._imported = None
            self.config.setText(path)
            self._probe()

    def _invalidate(self):
        self.validated = None
        self.cameras.clear()
        self.add.setEnabled(False)
        self.cameras.setEnabled(False)

    def _probe(self):
        if self.worker is not None:
            return
        try:
            profile = dict(self._imported or {}, installation=self.installation.text())
            if not profile.get("connection"):
                profile["config"] = self.config.text()
            profile = validate_profile(profile)
        except ValueError as exc:
            self.status.setText("Choose a Micro-Manager folder and a valid camera configuration.")
            self._set_details(str(exc))
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
        self.worker = worker
        self._update_actions()
        self.installation.setReadOnly(True)
        self.config.setReadOnly(True)
        self.status.setText(message)
        self._set_details("")
        self.cancel_search.setText("Cancel search" if isinstance(worker, CameraSearch) else "Cancel loading")
        self.cancel_search.show()
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
        worker.progress.connect(self.status.setToolTip)
        self._start_worker(worker, "Finding cameras… This can take up to a minute.")

    def _cancel_search(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.status.setText("Cancelling search; keeping cameras already found…" if isinstance(self.worker, CameraSearch)
                                else "Cancelling configuration loading…")

    def _found(self, details):
        for result in details["cameras"]:
            profile = result["profile"]
            self.cameras.addItem(profile.get("display_name", profile["camera"]), profile)
            self._controls[profile_key(profile)] = result["controls"]
        self.validated = {} if details["cameras"] else None
        count = len(details["cameras"])
        if count:
            self.cameras.setCurrentIndex(0)
        self.status.setText(f"Found {count} camera(s). Choose one and click Add camera." if count else
                            "No cameras found. Check the connection and drivers, or load a Micro-Manager configuration.")
        self._set_details("\n".join(details["issues"]))
        self._update_actions()

    def _loaded(self, details):
        self.validated = dict(self._pending_profile)
        self._configured_modes = details.get("modes", {})
        self.cameras.addItems(details["cameras"])
        self.cameras.setCurrentText(details["selected"])
        for camera, controls in details.get("controls", {}).items():
            self._controls[profile_key(dict(self.validated, camera=camera))] = controls
        self.status.setText("Configuration loaded. Choose a camera and click Add camera." if details["cameras"] else
                            "This configuration does not contain a camera. Choose a camera configuration.")
        self._set_details(f"{details['version']}\n{details['api']}\n\n"
                          "Start the camera in BURST to check preview. Setup does not verify recording synchronization.")
        self._update_actions()

    def _failed(self, message):
        self.validated = None
        self.cameras.clear()
        self.status.setText("Could not connect to the camera. Close other camera apps and check its drivers. "
                            "Open Details for the reported problem.")
        self._set_details(message + "\n\nUse Micro-Manager adapters compatible with this BURST build. "
                          "An older Micro-Manager installation may need updating.")
        self._update_actions()

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.cancel_search.hide()
        self.status.setToolTip("")
        self.installation.setReadOnly(False)
        self.config.setReadOnly(False)
        self.buttons.setEnabled(True)
        self._update_actions()
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
        self._update_actions()
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
            self.advanced_toggle.setChecked(True)
            self._update_actions()
            self.status.setText("Profile imported. Check the local paths under Advanced options, then click Check configuration.")
        except (ValueError, OSError) as exc:
            self.status.setText("Could not import this profile. Open Details for the reported problem.")
            self._set_details(str(exc))

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
                self.status.setText("Could not export this profile. Open Details for the reported problem.")
                self._set_details(str(exc))

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
