# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for BURST.

This spec collects the application icons and stylesheet so the GUI has a
consistent, polished look across all platforms.
"""

import os
import runpy
import importlib.util
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_entry_point

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
excluded_modules = []
for module in ("imagingcontrol4", "cv2", "harvesters", "genicam"):
    if _optional_module(module):
        datas, binaries, imports = collect_all(module)
        camera_data.extend(datas)
        camera_binaries.extend(binaries)
        hidden_imports.extend(imports)
    else:
        excluded_modules.append(module)

# Build-time opt-in: bundle the matching Python binding, but use the separately
# installed Spinnaker runtime. Never sweep Program Files for proprietary DLLs.
bundle_pyspin = os.environ.get("BURST_BUNDLE_PYSPIN", "0") == "1"
if bundle_pyspin:
    if not _optional_module("PySpin"):
        raise SystemExit("BURST_BUNDLE_PYSPIN=1 requires the SDK's matching PySpin wheel in the build environment.")
    hidden_imports.extend(["PySpin", "_PySpin"])
else:
    excluded_modules.extend(["PySpin", "_PySpin"])

plugin_datas, plugin_imports = collect_entry_point("burst.camera_backends")
camera_data.extend(plugin_datas)
hidden_imports.extend(plugin_imports)

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
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)

# Dependency analysis can pull runtime DLLs along with _PySpin.pyd. Leave files
# from Spinnaker installations out; the vendor runtime installer owns them.
def _external_spinnaker_file(entry):
    destination, source, *_ = entry
    path = str(source).replace("\\", "/").lower()
    name = Path(destination).name.lower()
    binding = name.endswith(".pyd") and "pyspin" in name
    runtime_path = "/spinnaker/" in path or "/pyspin/" in path
    runtime_name = name.endswith((".dll", ".cti")) and ("spinnaker" in name or name.startswith("flir_gentl"))
    return not binding and (runtime_path or runtime_name)

if bundle_pyspin:
    a.binaries = [entry for entry in a.binaries if not _external_spinnaker_file(entry)]
    a.datas = [entry for entry in a.datas if not _external_spinnaker_file(entry)]

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
