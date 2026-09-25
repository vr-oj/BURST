import importlib.util
import os
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

try:
    from PyInstaller.utils import hooks
except ImportError:
    hooks = None


@unittest.skipIf(hooks is None, "PyInstaller build tooling is not installed")
class CameraPackagingTests(unittest.TestCase):
    def run_spec(self, available=(), bundle=False):
        analysis = {}
        def analyze(*args, **kwargs):
            analysis.update(kwargs)
            return NS(pure=[], scripts=[], binaries=[], datas=[], zipfiles=[])
        with patch.object(importlib.util, "find_spec", side_effect=lambda name: NS() if name in available else None), \
             patch.object(hooks, "collect_all", side_effect=lambda name: ([], [], [name])), \
             patch.dict(os.environ, {"BURST_BUNDLE_PYSPIN": "1" if bundle else "0"}):
            result = runpy.run_path(str(Path(__file__).parents[1] / "BURST.spec"), init_globals={
                "Analysis": analyze, "PYZ": lambda *a, **kw: None,
                "EXE": lambda *a, **kw: None, "COLLECT": lambda *a, **kw: None,
            })
        return analysis, result

    def test_no_optional_sdk_does_not_abort_build(self):
        analysis, result = self.run_spec()
        self.assertIn("imagingcontrol4", analysis["excludes"])
        self.assertIn("PySpin", analysis["excludes"])

    def test_build_only_collects_ic4_and_mm_even_with_old_bindings_installed(self):
        analysis, result = self.run_spec({"imagingcontrol4", "pymmcore", "PySpin", "cv2", "harvesters", "genicam"}, bundle=True)
        self.assertIn("imagingcontrol4", analysis["hiddenimports"])
        self.assertIn("pymmcore", analysis["hiddenimports"])
        for name in ("PySpin", "_PySpin", "cv2", "harvesters", "genicam"):
            self.assertNotIn(name, analysis["hiddenimports"])
            self.assertIn(name, analysis["excludes"])

    def test_micro_manager_binding_is_bundled_when_available(self):
        analysis, _ = self.run_spec({"pymmcore"})
        self.assertIn("pymmcore", analysis["hiddenimports"])
        self.assertNotIn("pymmcore", analysis["excludes"])
        self.assertIn(os.path.join("buti_app", "hooks", "mm_worker_bootstrap.py"), analysis["runtime_hooks"])

    def test_external_plugin_bridge_is_shipped_as_source_without_vendor_bindings(self):
        analysis, _ = self.run_spec()
        self.assertIn((os.path.join("buti_app", "burst_camera_plugin", "*.py"),
                       os.path.join("buti_app", "burst_camera_plugin")), analysis["datas"])
        self.assertNotIn("adapter", analysis["hiddenimports"])
