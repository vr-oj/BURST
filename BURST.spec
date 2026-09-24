# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for BURST.

This spec collects the application resources for the Windows release build.
Other platforms require their own packaging and hardware validation.
"""

import os
import runpy
import importlib.util
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

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


def _optional_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


hidden_imports = ["PyQt5.QtMultimedia"]
camera_binaries = []
camera_data = []
# Cameras beyond IC4 use Micro-Manager's external adapters; never bundle the
# removed capture bridges, even when they exist on the build PC.
excluded_modules = ["PySpin", "_PySpin", "harvesters", "genicam", "cv2"]
for module in ("imagingcontrol4", "pymmcore"):
    if _optional_module(module):
        datas, binaries, imports = collect_all(module)
        camera_data.extend(datas)
        camera_binaries.extend(binaries)
        hidden_imports.extend(imports)
    else:
        excluded_modules.append(module)

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

data_files.extend(camera_data)


a = Analysis(
    [source_script],
    pathex=[],
    binaries=camera_binaries,
    datas=data_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join("buti_app", "hooks", "mm_worker_bootstrap.py")],
    excludes=excluded_modules,
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
