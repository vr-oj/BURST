import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OptionalCameraStartupTests(unittest.TestCase):
    def test_real_window_starts_and_closes_with_all_camera_sdks_blocked(self):
        root = Path(__file__).parents[1]
        code = r'''
import importlib.abc
import sys
class BlockCameraSDKs(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'imagingcontrol4', 'PySpin', 'cv2', 'harvesters', 'genicam', 'pymmcore'}:
            raise ImportError('deliberately unavailable for startup test')
sys.meta_path.insert(0, BlockCameraSDKs())
sys.path.insert(0, 'buti_app')
from PyQt5.QtWidgets import QApplication
from main_window import MainWindow
app = QApplication([])
window = MainWindow()
assert not window.camera_registry.backends
assert window.device_combo.count() == 1
window.close()
app.processEvents()
print('OPTIONAL_SDK_STARTUP_OK')
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", BURST_CAMERA_BACKEND="auto", BURST_RESULTS_DIR=directory)
            result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OPTIONAL_SDK_STARTUP_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
