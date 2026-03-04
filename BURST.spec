# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for BURST.

This spec collects the application icons and stylesheet so the GUI has a
consistent, polished look across all platforms.
"""

import os
from pathlib import Path

source_script = os.path.join("buti_app", "buti_app.py")
icon_file = os.path.join("buti_app", "ui", "icons", "BURST.ico")


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
    (os.path.join("buti_app", "ui", "icons", "*"), os.path.join("buti_app", "ui", "icons")),
    (os.path.join("buti_app", "ui", "style.qss"), os.path.join("buti_app", "ui")),
    (os.path.join("buti_app", "docs", "*"), os.path.join("buti_app", "docs")),
]

data_files.append((str(imagingcontrol4_root / "*"), "imagingcontrol4"))


a = Analysis(
    [source_script],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=["imagingcontrol4"],
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
    name="BURST 1.0",
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
