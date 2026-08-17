import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


app_path = str(Path(__file__).parents[1] / "buti_app")
sys.path.insert(0, app_path)
try:
    import main_window
finally:
    sys.path.remove(app_path)
    # ``main_window`` uses the source-launch import style and loads
    # buti_app/buti_app.py as the top-level ``buti_app`` module. Remove that
    # alias so package-style imports in the rest of the suite remain available.
    loaded_buti_app = sys.modules.get("buti_app")
    if loaded_buti_app is not None and not hasattr(loaded_buti_app, "__path__"):
        sys.modules.pop("buti_app", None)


class _CheckBox:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _CameraWidget:
    def __init__(self):
        self.mirroring = None

    def set_mirroring(self, horizontal, vertical):
        self.mirroring = (horizontal, vertical)


class CameraTransformSessionTests(unittest.TestCase):
    def test_transform_change_is_applied_without_becoming_an_app_setting(self):
        camera_widget = _CameraWidget()
        window = SimpleNamespace(
            _mirror_horizontal=False,
            _mirror_vertical=False,
            camera_info_panel=SimpleNamespace(
                mirror_horizontal_cb=_CheckBox(True),
                mirror_vertical_cb=_CheckBox(True),
            ),
            camera_widget=camera_widget,
        )

        with patch.object(main_window, "save_app_setting") as save_setting:
            main_window.MainWindow._on_camera_transform_changed(window)

        self.assertTrue(window._mirror_horizontal)
        self.assertTrue(window._mirror_vertical)
        self.assertEqual(camera_widget.mirroring, (True, True))
        save_setting.assert_not_called()


if __name__ == "__main__":
    unittest.main()
