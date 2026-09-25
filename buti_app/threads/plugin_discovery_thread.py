"""Bounded discovery outside the GUI; no native plugin code runs in this process."""
import time
from PyQt5.QtCore import QThread
from cameras.plugin_process import PluginCancelled


class PluginDiscoveryThread(QThread):
    def __init__(self, backends, parent=None):
        super().__init__(parent)
        self.backends = dict(backends)
        self.results, self.errors = {}, {}

    def run(self):
        deadline = time.monotonic() + 60
        for key, backend in self.backends.items():
            if self.isInterruptionRequested():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.errors[key] = "Search time limit reached. Refresh Devices to retry."
                continue
            try:
                self.results[key] = backend.probe(self.isInterruptionRequested, min(10, remaining))
            except PluginCancelled:
                break
            except Exception as exc:
                self.errors[key] = str(exc)
