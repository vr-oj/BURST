"""Keep Windows DLL search handles alive for externally installed SDK runtimes."""
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)
_dll_directories = {}


def configure_dll_paths():
    if not hasattr(os, "add_dll_directory"):
        return
    paths = [Path(p) for p in os.environ.get("BURST_CAMERA_DLL_PATH", "").split(os.pathsep) if p]
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    for vendor in ("Teledyne", "FLIR Systems", "FLIR"):
        for subdir in ("bin64", "bin64/vs2015"):
            paths.append(program_files / vendor / "Spinnaker" / subdir)
    for variable in ("GENICAM_GENTL64_PATH", "BURST_GENTL_PATH"):
        for entry in os.environ.get(variable, "").split(os.pathsep):
            if entry:
                path = Path(os.path.expandvars(entry.strip().strip('"')))
                paths.append(path.parent if path.suffix.lower() == ".cti" else path)
    for path in paths:
        if path.is_dir():
            resolved = str(path.resolve())
            if resolved not in _dll_directories:
                try:
                    _dll_directories[resolved] = os.add_dll_directory(resolved)
                except OSError as exc:
                    log.info("Camera SDK DLL directory unavailable (%s): %s", path, exc)
