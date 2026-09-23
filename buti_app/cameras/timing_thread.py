"""Switch timing inside the acquisition worker, with an explicit ready boundary."""
from queue import Queue, Empty
from PyQt5.QtCore import QThread, pyqtSignal


class TimingCameraThread(QThread):
    timing_ready = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timing_requests = Queue()
        self.trigger_configuration = {}

    def request_timing(self, source):
        # Called by the GUI; SDK operations remain on the acquisition thread.
        self._timing_requests.put(source)

    def service_timing(self, switch):
        try:
            source = self._timing_requests.get_nowait()
        except Empty:
            return False
        self.trigger_configuration = {}
        configuration = switch(source)
        if source and not configuration:
            raise RuntimeError("Camera did not confirm external triggering. Recording was not started.")
        self.trigger_configuration = configuration
        self.timing_ready.emit(bool(configuration))
        return True
