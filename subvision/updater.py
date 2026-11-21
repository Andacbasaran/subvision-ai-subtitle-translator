"""
SubVision AI — In-App Update Checker (GitHub Releases API).
Uses only Python stdlib (urllib + json) with strict timeouts so it never blocks
or degrades offline operation.
"""

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

from subvision import __repo__, __version__

GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{__repo__}/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    is_update_available: bool
    release_url: str
    release_notes: str = ""
    error: Optional[str] = None


def parse_semver(version_str: str) -> Tuple[int, int, int, int]:
    """
    Parses semantic version strings like 'v1.4.0', '1.4.0', '1.4.0-beta.1'.
    Returns (major, minor, patch, is_stable) where stable=1 > prerelease=0.
    """
    cleaned = (version_str or "").strip().lstrip("vV")
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].+)?$", cleaned)
    if not match:
        return (0, 0, 0, 0)
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    is_stable = 0 if "-" in cleaned else 1
    return (major, minor, patch, is_stable)


def is_newer_version(latest: str, current: str) -> bool:
    """Returns True if `latest` is strictly newer than `current`."""
    return parse_semver(latest) > parse_semver(current)


def check_for_updates(
    current_version: str = __version__,
    api_url: str = GITHUB_LATEST_RELEASE_URL,
    timeout_sec: float = 4.0,
) -> UpdateInfo:
    """
    Queries GitHub Releases API for the latest release and compares with current_version.
    Never raises — returns an UpdateInfo with `error` populated on network failure.
    """
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"SubVisionAI/{current_version}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        tag_name = str(payload.get("tag_name") or "").strip()
        latest_ver = tag_name.lstrip("vV") or current_version
        html_url = str(
            payload.get("html_url")
            or f"https://github.com/{__repo__}/releases/latest"
        )
        notes = str(payload.get("body") or "").strip()[:600]
        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_ver,
            is_update_available=is_newer_version(latest_ver, current_version),
            release_url=html_url,
            release_notes=notes,
        )
    except Exception as exc:
        return UpdateInfo(
            current_version=current_version,
            latest_version=current_version,
            is_update_available=False,
            release_url=f"https://github.com/{__repo__}/releases/latest",
            error=str(exc),
        )


try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class UpdateCheckerThread(QThread):
        """Runs GitHub update check asynchronously without blocking the Qt UI thread."""

        update_checked = pyqtSignal(object)  # emits UpdateInfo

        def __init__(self, current_version: str = __version__, parent=None):
            super().__init__(parent)
            self.current_version = current_version

        def run(self) -> None:
            info = check_for_updates(current_version=self.current_version)
            self.update_checked.emit(info)

except Exception:
    UpdateCheckerThread = None  # type: ignore[assignment,misc]
