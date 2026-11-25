#!/usr/bin/env python3
"""
SubVision AI — Linux & Steam Deck (SteamOS) Portable .tar.gz & AppImage Build Tool

Features:
1. Builds standalone PyInstaller (--onedir --windowed) bundle at 'dist/SubVisionAI'.
2. Packages portable archive 'dist/SubVisionAI-v<version>-Linux-<arch>.tar.gz' (always produced).
3. Assembles 'dist/SubVisionAI.AppDir' using packaging/linux/AppRun,
   packaging/linux/com.andacbasaran.SubVisionAI.desktop, and assets/app_icon.png.
4. If 'appimagetool' is available on PATH (and --skip-appimage is not set), builds
   'dist/SubVisionAI-v<version>-Linux-<arch>.AppImage'.
5. Writes 'dist/SHA256SUMS-Linux.txt' for all produced Linux release artifacts.

Usage:
    python scripts/build_linux.py
    python scripts/build_linux.py --version 1.6.0 --arch x86_64
    python scripts/build_linux.py --version 1.6.0 --skip-appimage
"""

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from typing import List, Optional

APP_NAME = "SubVisionAI"
DESKTOP_ID = "com.andacbasaran.SubVisionAI.desktop"
ICON_NAME = "subvision-ai"
DEFAULT_VERSION = "1.6.0"

SUBVISION_HIDDEN_IMPORTS = [
    "subvision",
    "subvision.audio_whisper",
    "subvision.context_translator",
    "subvision.custom_glossary",
    "subvision.exporters",
    "subvision.glossary",
    "subvision.glossary_hub",
    "subvision.hardware",
    "subvision.i18n",
    "subvision.language_packs",
    "subvision.ocr_engine",
    "subvision.overlay_ui",
    "subvision.profiles",
    "subvision.translator",
    "subvision.ui_widgets",
    "subvision.updater",
    "subvision.vocab_learner",
    "subvision.window_tracker",
    "subvision.workers",
    "rapidocr_onnxruntime",
    "ctranslate2",
    "sentencepiece",
    "mss",
    "cv2",
]


def read_project_version(base_dir: str) -> str:
    pyproject = os.path.join(base_dir, "pyproject.toml")
    if os.path.exists(pyproject):
        with open(pyproject, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_onedir_bundle(base_dir: str) -> str:
    print(f"[1/4] Building PyInstaller --onedir bundle '{APP_NAME}'...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "ctranslate2",
        "--collect-all",
        "onnxruntime",
        "--collect-all",
        "sentencepiece",
        "--collect-submodules",
        "subvision",
    ]

    for mod in SUBVISION_HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", mod])

    assets_dir = os.path.join(base_dir, "assets")
    if os.path.isdir(assets_dir):
        cmd.extend(["--add-data", f"{assets_dir}:assets"])

    glossaries_dir = os.path.join(base_dir, "glossaries")
    if os.path.isdir(glossaries_dir):
        cmd.extend(["--add-data", f"{glossaries_dir}:glossaries"])

    cmd.append(os.path.join(base_dir, "main.py"))

    env = os.environ.copy()
    pyi_cache = os.path.join(base_dir, "build", "pyinstaller_cache")
    os.makedirs(pyi_cache, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = pyi_cache

    subprocess.run(cmd, cwd=base_dir, env=env, check=True)

    bundle_dir = os.path.join(base_dir, "dist", APP_NAME)
    if not os.path.isdir(bundle_dir):
        raise RuntimeError(f"Expected PyInstaller bundle directory not found: {bundle_dir}")
    print(f"[OK] PyInstaller bundle ready: {bundle_dir}")
    return bundle_dir


def create_tarball(base_dir: str, bundle_dir: str, version: str, arch: str) -> str:
    tar_name = f"SubVisionAI-v{version}-Linux-{arch}.tar.gz"
    tar_path = os.path.join(base_dir, "dist", tar_name)
    if os.path.exists(tar_path):
        os.remove(tar_path)

    print(f"[2/4] Packaging portable archive: {tar_name} ...")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=APP_NAME)

    size_mb = os.path.getsize(tar_path) / (1024 * 1024)
    print(f"[OK] Portable archive ready: {tar_path} ({size_mb:.1f} MB)")
    return tar_path


def assemble_appdir(base_dir: str, bundle_dir: str) -> str:
    print("[3/4] Assembling dist/SubVisionAI.AppDir ...")
    appdir = os.path.join(base_dir, "dist", f"{APP_NAME}.AppDir")
    if os.path.exists(appdir):
        shutil.rmtree(appdir)

    usr_bin = os.path.join(appdir, "usr", "bin")
    usr_apps = os.path.join(appdir, "usr", "share", "applications")
    usr_icons = os.path.join(appdir, "usr", "share", "icons", "hicolor", "256x256", "apps")
    os.makedirs(usr_apps, exist_ok=True)
    os.makedirs(usr_icons, exist_ok=True)

    shutil.copytree(bundle_dir, usr_bin, symlinks=True)

    apprun_src = os.path.join(base_dir, "packaging", "linux", "AppRun")
    apprun_dst = os.path.join(appdir, "AppRun")
    shutil.copy2(apprun_src, apprun_dst)
    os.chmod(
        apprun_dst,
        os.stat(apprun_dst).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
    )

    desktop_src = os.path.join(base_dir, "packaging", "linux", DESKTOP_ID)
    shutil.copy2(desktop_src, os.path.join(appdir, DESKTOP_ID))
    shutil.copy2(desktop_src, os.path.join(usr_apps, DESKTOP_ID))

    icon_src = os.path.join(base_dir, "assets", "app_icon.png")
    if os.path.exists(icon_src):
        shutil.copy2(icon_src, os.path.join(appdir, f"{ICON_NAME}.png"))
        shutil.copy2(icon_src, os.path.join(appdir, ".DirIcon"))
        shutil.copy2(icon_src, os.path.join(usr_icons, f"{ICON_NAME}.png"))
    else:
        print("[WARN] assets/app_icon.png not found; AppDir created without icon.")

    print(f"[OK] AppDir assembled: {appdir}")
    return appdir


def build_appimage(base_dir: str, appdir: str, version: str, arch: str) -> Optional[str]:
    tool = shutil.which("appimagetool")
    if not tool:
        print("[INFO] 'appimagetool' not found on PATH; skipping AppImage generation.")
        return None

    appimage_name = f"SubVisionAI-v{version}-Linux-{arch}.AppImage"
    appimage_path = os.path.join(base_dir, "dist", appimage_name)
    if os.path.exists(appimage_path):
        os.remove(appimage_path)

    print(f"[4/4] Building AppImage: {appimage_name} ...")
    env = os.environ.copy()
    env["ARCH"] = arch
    subprocess.run([tool, appdir, appimage_path], cwd=base_dir, env=env, check=True)

    size_mb = os.path.getsize(appimage_path) / (1024 * 1024)
    print(f"[OK] AppImage ready: {appimage_path} ({size_mb:.1f} MB)")
    return appimage_path


def write_checksums(base_dir: str, artifacts: List[str]) -> str:
    sums_path = os.path.join(base_dir, "dist", "SHA256SUMS-Linux.txt")
    lines = []
    for path in artifacts:
        digest = sha256_file(path)
        name = os.path.basename(path)
        lines.append(f"{digest}  {name}\n")
        print(f"[OK] SHA-256 ({name}): {digest}")

    with open(sums_path, "w", encoding="ascii") as f:
        f.writelines(lines)
    print(f"[OK] Checksums written: {sums_path}")
    return sums_path


def main() -> int:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(
        description="Build SubVision AI Linux portable .tar.gz and AppImage"
    )
    parser.add_argument(
        "--version",
        default=read_project_version(base_dir),
        help="Release version (default: read from pyproject.toml or 1.6.0)",
    )
    parser.add_argument(
        "--arch",
        default="x86_64",
        choices=["x86_64", "aarch64"],
        help="Target architecture (default: x86_64)",
    )
    parser.add_argument(
        "--skip-appimage",
        action="store_true",
        help="Assemble AppDir but skip running appimagetool",
    )
    args = parser.parse_args()
    version = args.version.lstrip("v")

    if not sys.platform.startswith("linux"):
        print("[ERROR] build_linux.py must be run on Linux.")
        return 1

    bundle_dir = build_onedir_bundle(base_dir)
    artifacts: List[str] = []

    tar_path = create_tarball(base_dir, bundle_dir, version, args.arch)
    artifacts.append(tar_path)

    appdir = assemble_appdir(base_dir, bundle_dir)
    if not args.skip_appimage:
        appimage_path = build_appimage(base_dir, appdir, version, args.arch)
        if appimage_path:
            artifacts.append(appimage_path)
    else:
        print("[4/4] Skipping AppImage packaging (--skip-appimage).")

    write_checksums(base_dir, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
