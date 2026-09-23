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
            return NS(pure=[], scripts=[], binaries=[
                ("Spinnaker_v140.dll", "C:/Program Files/Teledyne/Spinnaker/bin64/Spinnaker_v140.dll", "BINARY"),
                ("_PySpin.pyd", "C:/venv/Lib/site-packages/_PySpin.pyd", "EXTENSION"),
            ], datas=[], zipfiles=[])
        with patch.object(importlib.util, "find_spec", side_effect=lambda name: NS() if name in available else None), \
             patch.object(hooks, "collect_all", side_effect=lambda name: ([], [], [name])), \
             patch.object(hooks, "collect_entry_point", return_value=([], ["example_camera_plugin"])), \
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
        self.assertIn("example_camera_plugin", analysis["hiddenimports"])

    def test_available_ic4_and_opted_in_pyspin_are_packaged_without_runtime(self):
        analysis, result = self.run_spec({"imagingcontrol4", "PySpin"}, bundle=True)
        self.assertIn("imagingcontrol4", analysis["hiddenimports"])
        self.assertIn("PySpin", analysis["hiddenimports"])
        self.assertEqual([entry[0] for entry in result["a"].binaries], ["_PySpin.pyd"])

    def test_explicit_pyspin_request_explains_missing_wheel(self):
        with self.assertRaisesRegex(SystemExit, "matching PySpin wheel"):
            self.run_spec(bundle=True)

    def test_micro_manager_binding_is_bundled_when_available(self):
        analysis, _ = self.run_spec({"pymmcore"})
        self.assertIn("pymmcore", analysis["hiddenimports"])
        self.assertNotIn("pymmcore", analysis["excludes"])
        self.assertIn(os.path.join("buti_app", "hooks", "mm_worker_bootstrap.py"), analysis["runtime_hooks"])
