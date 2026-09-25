"""Optional lab-developer route; no changes to the everyday camera toolbar."""
from PyQt5.QtCore import QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton, QDialogButtonBox
from cameras.plugins import plugin_directory, plugin_roots


class CameraPluginsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Camera plugins")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        text = QLabel("For labs using a developer-provided SDK adapter. Install the plugin and its Python/SDK "
                      "environment following the lab's instructions, then refresh cameras. "
                      "Plugins run code on this computer; install only plugins you trust. "
                      "IC4 and Micro-Manager do not require a plugin.")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        layout.addWidget(self.status)
        folder = QPushButton("Open plugin folder")
        folder.clicked.connect(self._folder)
        layout.addWidget(folder)
        guide = QPushButton("Developer guide")
        guide.clicked.connect(self._guide)
        layout.addWidget(guide)
        self.refresh = QPushButton("Refresh plugin cameras")
        self.refresh.clicked.connect(window._refresh_plugin_cameras)
        layout.addWidget(self.refresh)
        self.cancel = QPushButton("Cancel search")
        self.cancel.clicked.connect(self._cancel)
        layout.addWidget(self.cancel)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update)
        self.timer.start(300)
        self._update()

    def _update(self):
        search = self.window._plugin_search
        searching = search is not None and search.isRunning()
        self.cancel.setVisible(searching)
        self.refresh.setEnabled(not searching and self.window.camera_thread is None
                                and self.window._recording_state == "idle")
        lines = ["Plugin folders:", *(str(p) for p in plugin_roots()), ""]
        lines.append("Searching…" if searching else "Installed plugins:")
        for key, backend in self.window.camera_registry.backends.items():
            if key.startswith("plugin:"):
                lines.append(f"{backend.manifest.name} {backend.manifest.version}: {len(backend.devices)} camera(s)")
        for path, error in self.window.camera_registry.plugin_errors.items():
            lines.extend(("", str(path), error))
        contents = "\n".join(lines)
        if contents != self.status.toPlainText():
            self.status.setPlainText(contents)

    def _folder(self):
        folder = plugin_roots()[0] if plugin_roots() else plugin_directory()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _guide(self):
        from utils.path_helpers import resource_path
        QDesktopServices.openUrl(QUrl.fromLocalFile(resource_path("docs", "camera-plugins.md")))

    def _cancel(self):
        if self.window._plugin_search is not None:
            self.window._plugin_search.requestInterruption()
