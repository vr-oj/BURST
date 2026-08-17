# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for BURST.

This spec collects the application icons and stylesheet so the GUI has a
consistent, polished look across all platforms.
"""

import os
import runpy
from pathlib import Path

source_script = os.path.join("buti_app", "buti_app.py")
icon_file = os.path.join("buti_app", "ui", "icons", "BURST.ico")
version_scope = runpy.run_path(os.path.join("buti_app", "utils", "version.py"))
app_version = version_scope["APP_VERSION"]


def _write_windows_version_resource():
    if os.name != "nt":
        return None

    version_path = Path("build") / "BURST-version-info.txt"
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text(
        version_scope["render_windows_version_info"](app_version),
        encoding="utf-8",
    )
    return str(version_path)


version_resource = _write_windows_version_resource()


def _find_imagingcontrol4_root():
    try:
        import importlib.util
        spec = importlib.util.find_spec("imagingcontrol4")
        if spec and spec.submodule_search_locations:
            root = Path(spec.submodule_search_locations[0])
            if root.exists():
                return root
    except (ImportError, ValueError):
        pass
    return None


imagingcontrol4_root = _find_imagingcontrol4_root()
if imagingcontrol4_root is None:
    raise SystemExit(
        "Unable to locate the imagingcontrol4 package. Install it into your active virtual environment before building."
    )

data_files = [
    (
        os.path.join("buti_app", "ui", "icons", "*"),
        os.path.join("buti_app", "ui", "icons"),
    ),
    (os.path.join("buti_app", "ui", "style.qss"), os.path.join("buti_app", "ui")),
    (
        os.path.join("buti_app", "ui", "sounds", "*"),
        os.path.join("buti_app", "ui", "sounds"),
    ),
    (os.path.join("buti_app", "docs", "*"), os.path.join("buti_app", "docs")),
    (os.path.join("buti_app", "VERSION"), "buti_app"),
]

data_files.append((str(imagingcontrol4_root / "*"), "imagingcontrol4"))


a = Analysis(
    [source_script],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=["imagingcontrol4", "PyQt5.QtMultimedia"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BURST",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=version_resource,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BURST",
)
