"""Background GitHub release checks for BURST."""

from __future__ import annotations

import logging
import ssl
import urllib.request
from urllib.parse import unquote, urlparse

import certifi
from PyQt5.QtCore import QThread, pyqtSignal

from utils.version import parse_version


log = logging.getLogger(__name__)


def normalized_release_version(tag: str) -> str:
    """Return a validated BURST version from a GitHub tag such as ``v1.3.0``."""

    version = (tag or "").strip()
    if version.lower().startswith("v"):
        version = version[1:]
    parse_version(version)
    return version


def version_sort_key(version: str) -> tuple[int, int, int, int, int]:
    """Return a comparison key where prereleases sort before the final release."""

    major, minor, patch, stage, stage_number = parse_version(
        normalized_release_version(version)
    )
    stage_rank = {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage]
    return major, minor, patch, stage_rank, stage_number or 0


def is_version_newer(remote_tag: str, current_version: str) -> bool:
    """Return whether ``remote_tag`` is newer than the installed version."""

    return version_sort_key(remote_tag) > version_sort_key(current_version)


def release_tag_from_url(url: str) -> str:
    """Extract and validate the tag from a redirected GitHub release URL."""

    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) < 2 or path_parts[-2].lower() != "tag":
        raise ValueError(f"Unexpected GitHub release URL: {url}")
    tag = unquote(path_parts[-1])
    normalized_release_version(tag)
    return tag


def resolve_latest_release(
    release_url: str,
    *,
    current_version: str,
    timeout: float = 5.0,
    urlopen=urllib.request.urlopen,
) -> tuple[str, str]:
    """Resolve GitHub's latest-release redirect to ``(tag, final_url)``."""

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(
        release_url,
        headers={"User-Agent": f"BURST/{current_version}"},
    )
    with urlopen(request, context=ssl_context, timeout=timeout) as response:
        final_url = response.geturl()
    return release_tag_from_url(final_url), final_url


class UpdateChecker(QThread):
    """Check GitHub in the background without delaying application startup."""

    update_available = pyqtSignal(str, str)
    check_failed = pyqtSignal(str)

    def __init__(
        self,
        current_version: str,
        release_url: str,
        *,
        timeout: float = 5.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.current_version = current_version
        self.release_url = release_url
        self.timeout = timeout

    def run(self) -> None:
        try:
            latest_tag, final_url = resolve_latest_release(
                self.release_url,
                current_version=self.current_version,
                timeout=self.timeout,
            )
            if self.isInterruptionRequested():
                return
            if is_version_newer(latest_tag, self.current_version):
                self.update_available.emit(latest_tag, final_url)
        except Exception as exc:
            log.warning("Update check failed: %s", exc)
            self.check_failed.emit(str(exc))
