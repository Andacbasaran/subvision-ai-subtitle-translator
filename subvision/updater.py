"""
SubVision AI — Cross-Platform GitHub Releases Auto-Updater (Windows & macOS).

Uses only Python stdlib (urllib, json, hashlib, subprocess, tempfile) with strict
timeouts so it never blocks or degrades offline operation.

Flow:
  1. Queries GitHub Releases API for the latest release and selects the matching
     platform installer asset (.exe on Windows, .dmg on macOS arm64/x86_64) plus
     its SHA256SUMS file when published.
  2. Streams the installer in a background QThread with progress reporting and
     verifies SHA-256 integrity before applying.
  3. Applies the update cleanly and relaunches the app:
     - Windows: Launches Inno Setup installer with /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS
     - macOS:   Mounts the .dmg, atomically replaces the running .app bundle, clears
                quarantine attribute, and relaunches the updated app (falls back to
                opening the .dmg in Finder if not running from a writable .app bundle).
"""

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

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
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    checksum_url: str = ""

    @property
    def has_direct_installer(self) -> bool:
        return bool(self.asset_url and self.asset_name)


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


def select_platform_asset(
    assets: List[Dict],
    platform_name: Optional[str] = None,
    machine: Optional[str] = None,
) -> Tuple[str, str, int, str]:
    """
    Selects the best installer asset and matching SHA256SUMS URL from GitHub Release
    `assets` list for the given OS/architecture.

    Returns: (asset_name, asset_url, asset_size, checksum_url)
    """
    if not isinstance(assets, list):
        return ("", "", 0, "")

    plat = (platform_name or sys.platform).lower()
    arch = (machine or platform.machine() or "").lower()
    is_arm64 = arch in ("arm64", "aarch64")

    best_asset: Optional[Dict] = None
    best_score = -1
    checksum_macos = ""
    checksum_generic = ""

    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        low = name.lower()

        if "sha256" in low and low.endswith(".txt"):
            if "macos" in low or "darwin" in low:
                checksum_macos = url
            else:
                checksum_generic = url
            continue

        score = -1
        if plat == "darwin":
            if low.endswith(".dmg"):
                score = 10
                if is_arm64 and ("arm64" in low or "apple-silicon" in low):
                    score = 30
                elif (not is_arm64) and ("x86_64" in low or "x64" in low or "intel" in low):
                    score = 30
                elif "universal" in low:
                    score = 20
        elif plat == "win32":
            if low.endswith(".exe"):
                if "setup" in low and "online" not in low:
                    score = 30
                elif "onlinesetup" in low or "online" in low:
                    score = 20
                else:
                    score = 10

        if score > best_score:
            best_score = score
            best_asset = item

    if not best_asset:
        return ("", "", 0, "")

    checksum_url = (checksum_macos or checksum_generic) if plat == "darwin" else checksum_generic
    return (
        str(best_asset.get("name") or ""),
        str(best_asset.get("browser_download_url") or ""),
        int(best_asset.get("size") or 0),
        checksum_url,
    )


def parse_sha256sums(sums_text: str, target_filename: str) -> Optional[str]:
    """Extracts the expected lowercase SHA-256 hex digest for `target_filename`."""
    target_base = os.path.basename(target_filename).strip().lower()
    for line in (sums_text or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            digest = parts[0].strip().lower()
            fname = os.path.basename(parts[-1].lstrip("*")).strip().lower()
            if fname == target_base and re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return None


def compute_file_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_file_sha256(file_path: str, expected_hex: str) -> bool:
    if not expected_hex or not os.path.isfile(file_path):
        return False
    return compute_file_sha256(file_path) == expected_hex.strip().lower()


def check_for_updates(
    current_version: str = __version__,
    api_url: str = GITHUB_LATEST_RELEASE_URL,
    timeout_sec: float = 5.0,
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
        notes = str(payload.get("body") or "").strip()[:800]
        asset_name, asset_url, asset_size, checksum_url = select_platform_asset(
            payload.get("assets") or []
        )
        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_ver,
            is_update_available=is_newer_version(latest_ver, current_version),
            release_url=html_url,
            release_notes=notes,
            asset_name=asset_name,
            asset_url=asset_url,
            asset_size=asset_size,
            checksum_url=checksum_url,
        )
    except Exception as exc:
        return UpdateInfo(
            current_version=current_version,
            latest_version=current_version,
            is_update_available=False,
            release_url=f"https://github.com/{__repo__}/releases/latest",
            error=str(exc),
        )


def download_update_asset(
    info: UpdateInfo,
    dest_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    timeout_sec: float = 20.0,
) -> str:
    """
    Downloads the platform update installer from GitHub Releases into `dest_dir`,
    verifies SHA-256 if a checksum file is published, and returns the final file path.
    Raises RuntimeError on cancellation or integrity failure.
    """
    if not info.has_direct_installer:
        raise RuntimeError("Bu platform için doğrudan kurulum paketi bulunamadı.")

    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(info.asset_name)
    final_path = os.path.join(dest_dir, safe_name)
    part_path = final_path + ".part"

    req = urllib.request.Request(
        info.asset_url,
        headers={"User-Agent": f"SubVisionAI/{info.current_version}"},
    )
    downloaded = 0
    total = int(info.asset_size or 0)

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if total <= 0:
                hdr_len = resp.headers.get("Content-Length")
                if hdr_len and hdr_len.isdigit():
                    total = int(hdr_len)
            with open(part_path, "wb") as out:
                while True:
                    if cancel_check and cancel_check():
                        raise RuntimeError("Güncelleme indirmesi iptal edildi.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)

        if info.checksum_url:
            if status_cb:
                status_cb("SHA-256 bütünlüğü doğrulanıyor...")
            try:
                cs_req = urllib.request.Request(
                    info.checksum_url,
                    headers={"User-Agent": f"SubVisionAI/{info.current_version}"},
                )
                with urllib.request.urlopen(cs_req, timeout=10.0) as cs_resp:
                    sums_text = cs_resp.read().decode("utf-8", errors="replace")
                expected = parse_sha256sums(sums_text, safe_name)
                if expected and not verify_file_sha256(part_path, expected):
                    raise RuntimeError(
                        "İndirilen güncelleme dosyasının SHA-256 doğrulaması başarısız oldu."
                    )
            except RuntimeError:
                raise
            except Exception:
                # Checksum dosyası geçici olarak erişilemezse indirmeyi bozma
                pass

        os.replace(part_path, final_path)
        return final_path
    except Exception:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        raise


def _find_running_macos_app_bundle() -> Optional[str]:
    """Returns '/Applications/SubVision AI.app' if running inside a frozen macOS .app bundle."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    exe = os.path.abspath(sys.executable)
    marker = ".app/Contents/"
    idx = exe.find(marker)
    if idx == -1:
        return None
    return exe[: idx + 4]


def apply_downloaded_update(installer_path: str) -> Tuple[bool, str]:
    """
    Launches the platform-native update installation and prepares the app to exit.
    Returns `(should_exit_app, user_message)`.
    """
    if not os.path.isfile(installer_path):
        return (False, f"Güncelleme dosyası bulunamadı: {installer_path}")

    if sys.platform == "win32":
        low = installer_path.lower()
        if low.endswith(".exe"):
            cmd = [installer_path]
            if "setup" in os.path.basename(low) and "online" not in os.path.basename(low):
                cmd.extend(["/SP-", "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
            return (True, "Windows kurulum yardımcısı başlatıldı. Uygulama güncellenip yeniden açılacak.")
        os.startfile(installer_path)  # type: ignore[attr-defined]
        return (False, "Güncelleme paketi açıldı.")

    if sys.platform == "darwin":
        app_bundle = _find_running_macos_app_bundle()
        if (
            app_bundle
            and installer_path.lower().endswith(".dmg")
            and os.access(os.path.dirname(app_bundle), os.W_OK)
        ):
            pid = os.getpid()
            script_fd, script_path = tempfile.mkstemp(prefix="subvision_updater_", suffix=".sh")
            mount_dir = tempfile.mkdtemp(prefix="subvision_mnt_")
            q_dmg = shlex.quote(installer_path)
            q_app = shlex.quote(app_bundle)
            q_app_new = shlex.quote(app_bundle + ".new")
            q_app_old = shlex.quote(app_bundle + ".old")
            q_mnt = shlex.quote(mount_dir)
            q_script = shlex.quote(script_path)

            script_body = f"""#!/bin/bash
set -e
OLD_PID={pid}
while kill -0 "$OLD_PID" 2>/dev/null; do
    sleep 0.3
done

cleanup() {{
    hdiutil detach {q_mnt} -quiet 2>/dev/null || true
    rmdir {q_mnt} 2>/dev/null || true
    rm -f {q_script} 2>/dev/null || true
}}
trap cleanup EXIT

hdiutil attach {q_dmg} -nobrowse -quiet -mountpoint {q_mnt}
SRC_APP="$(find {q_mnt} -maxdepth 1 -name '*.app' -print -quit)"
if [ -z "$SRC_APP" ]; then
    open {q_dmg}
    exit 1
fi

rm -rf {q_app_new} {q_app_old}
ditto "$SRC_APP" {q_app_new}
xattr -dr com.apple.quarantine {q_app_new} 2>/dev/null || true

if [ -d {q_app} ]; then
    mv {q_app} {q_app_old}
fi
mv {q_app_new} {q_app}
rm -rf {q_app_old}
rm -f {q_dmg} 2>/dev/null || true

open -n {q_app}
"""
            with os.fdopen(script_fd, "w", encoding="utf-8") as f:
                f.write(script_body)
            os.chmod(script_path, 0o700)
            subprocess.Popen(
                ["/bin/bash", script_path],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return (True, "macOS güncellemesi uygulanıyor. Uygulama kapanıp yeni sürümle yeniden açılacak.")

        # Geliştirme ortamı veya yazma izni olmayan konum: DMG'yi Finder'da aç
        subprocess.Popen(["open", installer_path], start_new_session=True)
        return (False, "DMG paketi Finder'da açıldı. Yeni sürümü Applications klasörüne sürükleyebilirsiniz.")

    # Linux vb.
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, installer_path], start_new_session=True)
    return (False, f"Güncelleme indirildi: {installer_path}")


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

    class UpdateDownloadThread(QThread):
        """Downloads and verifies a GitHub Release installer in the background."""

        progress_changed = pyqtSignal(int, int)  # downloaded_bytes, total_bytes
        status_changed = pyqtSignal(str)
        download_finished = pyqtSignal(str, str)  # installer_path, error_msg

        def __init__(self, info: UpdateInfo, dest_dir: str, parent=None):
            super().__init__(parent)
            self.info = info
            self.dest_dir = dest_dir
            self._cancelled = False

        def cancel(self) -> None:
            self._cancelled = True

        def run(self) -> None:
            try:
                path = download_update_asset(
                    info=self.info,
                    dest_dir=self.dest_dir,
                    progress_cb=lambda dl, tot: self.progress_changed.emit(int(dl), int(tot)),
                    status_cb=lambda msg: self.status_changed.emit(str(msg)),
                    cancel_check=lambda: self._cancelled,
                )
                self.download_finished.emit(path, "")
            except Exception as exc:
                self.download_finished.emit("", str(exc))

except Exception:
    UpdateCheckerThread = None  # type: ignore[assignment,misc]
    UpdateDownloadThread = None  # type: ignore[assignment,misc]
