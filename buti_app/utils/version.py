"""Single-source BURST application version handling."""

from __future__ import annotations

import re
import sys
from pathlib import Path


VERSION_PATTERN = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?$"
)


def parse_version(version: str) -> tuple[int, int, int, str | None, int | None]:
    """Parse BURST's supported semantic-version format."""

    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(
            f"Invalid BURST version {version!r}; expected X.Y.Z or "
            "X.Y.Z-alpha.N, X.Y.Z-beta.N, or X.Y.Z-rc.N"
        )
    major, minor, patch, stage, stage_number = match.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        stage,
        int(stage_number) if stage_number is not None else None,
    )


def _version_file_path() -> Path:
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "buti_app" / "VERSION"
    return Path(__file__).resolve().parents[1] / "VERSION"


def load_app_version() -> str:
    """Read and validate the version bundled with the application."""

    version = _version_file_path().read_text(encoding="utf-8").strip()
    parse_version(version)
    return version


def windows_version_tuple(version: str) -> tuple[int, int, int, int]:
    """Return the four numeric components required by Windows resources."""

    major, minor, patch, stage, stage_number = parse_version(version)
    if stage is None:
        build = 65535
    else:
        stage_offsets = {"alpha": 1000, "beta": 2000, "rc": 3000}
        build = stage_offsets[stage] + stage_number
    if build > 65535:
        raise ValueError("The prerelease number is too large for Windows metadata")
    return major, minor, patch, build


def render_windows_version_info(version: str) -> str:
    """Render a PyInstaller-compatible Windows version resource."""

    numeric_version = windows_version_tuple(version)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric_version!r},
    prodvers={numeric_version!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'BUTI Lab'),
          StringStruct(u'FileDescription', u'BURST'),
          StringStruct(u'FileVersion', u'{version}'),
          StringStruct(u'InternalName', u'BURST'),
          StringStruct(u'OriginalFilename', u'BURST.exe'),
          StringStruct(u'ProductName', u'BURST'),
          StringStruct(u'ProductVersion', u'{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


APP_VERSION = load_app_version()
