#!/usr/bin/env python3
"""
SubVision AI — macOS (Apple Silicon arm64) .app & .dmg Kurulum Paketi Derleme Aracı

Özellikler:
1. assets/app_icon.png dosyasından otomatik macOS .icns ikonu üretir (yoksa).
2. PyInstaller (--onedir --windowed) ile bağımsız 'dist/SubVision AI.app' paketini derler.
3. Info.plist içine Ekran Kaydı (NSScreenCaptureUsageDescription), Mikrofon (Whisper) ve
   Retina (NSHighResolutionCapable) meta verilerini işler.
4. Paketi ad-hoc (veya MACOS_SIGN_IDENTITY ortam değişkeni varsa Developer ID ile) imzalar.
5. Sürükle-bırak ('SubVision AI.app' -> 'Applications') kurulumu ve ilk açılış rehberi içeren
   sıkıştırılmış .dmg kurulum dosyasını ve SHA-256 özetini üretir.

Kullanım:
    python scripts/build_macos.py
    python scripts/build_macos.py --version 1.6.0
    python scripts/build_macos.py --skip-dmg
"""

import argparse
import hashlib
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Optional

APP_NAME = "SubVision AI"
BUNDLE_ID = "com.andacbasaran.subvisionai"
DEFAULT_VERSION = "1.6.0"

FIRST_LAUNCH_GUIDE = """\
========================================================================
SubVision AI — macOS Kurulum ve İlk Açılış Rehberi
========================================================================

1. KURULUM
   "SubVision AI.app" simgesini "Applications" klasörüne sürükleyip bırakın.

2. İLK AÇILIŞ (macOS Gatekeeper Uyarısı)
   SubVision AI açık kaynaklı ve ücretsiz bir proje olduğu için Apple'ın
   ücretli Developer ID notarization sistemine kayıtlı değildir.
   İlk açılışta macOS "geliştirici doğrulanamadı" veya "açılamıyor" uyarısı
   verirse şu iki yoldan birini kullanabilirsiniz:

   Yöntem A (Sistem Ayarları):
   - Uygulamayı açmayı deneyin ve uyarıyı kapatın.
   - Sistem Ayarları -> Gizlilik ve Güvenlik bölümüne gidin.
   - En altta "SubVision AI engellendi" satırının yanındaki "Yine de Aç"
     düğmesine tıklayın.

   Yöntem B (Terminal — Tek Komut):
   xattr -cr "/Applications/SubVision AI.app"

3. EKRAN KAYDI İZNİ (Gerekli)
   Altyazı okuma (OCR) özelliğinin çalışması için:
   Sistem Ayarları -> Gizlilik ve Güvenlik -> Ekran ve Sistem Sesi Kaydı
   bölümünden "SubVision AI" uygulamasını etkinleştirin ve uygulamayı
   yeniden başlatın.

4. VERİ VE MODEL KONUMU
   İndirilen çeviri modeli ve ayarlarınız şu klasörde saklanır:
   ~/Library/Application Support/SubVisionAI

------------------------------------------------------------------------
English Quick Guide:
1. Drag "SubVision AI.app" into "Applications".
2. If macOS Gatekeeper blocks the first launch, run in Terminal:
   xattr -cr "/Applications/SubVision AI.app"
   or open System Settings -> Privacy & Security -> "Open Anyway".
3. Grant Screen Recording permission in System Settings -> Privacy &
   Security -> Screen & System Audio Recording, then restart the app.
========================================================================
"""


def read_project_version(base_dir: str) -> str:
    pyproject = os.path.join(base_dir, "pyproject.toml")
    if os.path.exists(pyproject):
        with open(pyproject, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def ensure_icns_icon(base_dir: str) -> Optional[str]:
    assets_dir = os.path.join(base_dir, "assets")
    icns_path = os.path.join(assets_dir, "app_icon.icns")
    png_path = os.path.join(assets_dir, "app_icon.png")

    if os.path.exists(icns_path) and os.path.getsize(icns_path) > 1024:
        return icns_path

    if not os.path.exists(png_path):
        print("[UYARI] assets/app_icon.png bulunamadı, varsayılan ikon kullanılacak.")
        return None

    print("[1/5] assets/app_icon.png dosyasından macOS app_icon.icns üretiliyor...")
    tmp_dir = tempfile.mkdtemp(prefix="subvision_icns_")
    try:
        mapping = [
            (b"icp4", 16, "icon_16.png"),
            (b"ic11", 32, "icon_16@2x.png"),
            (b"icp5", 32, "icon_32.png"),
            (b"ic12", 64, "icon_32@2x.png"),
            (b"ic07", 128, "icon_128.png"),
            (b"ic13", 256, "icon_128@2x.png"),
            (b"ic08", 256, "icon_256.png"),
            (b"ic14", 512, "icon_256@2x.png"),
            (b"ic09", 512, "icon_512.png"),
            (b"ic10", 1024, "icon_512@2x.png"),
        ]
        chunks = []
        for ostype, px, fname in mapping:
            out_png = os.path.join(tmp_dir, fname)
            subprocess.run(
                ["sips", "-s", "format", "png", "-z", str(px), str(px), png_path, "--out", out_png],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with open(out_png, "rb") as f:
                data = f.read()
            chunks.append(ostype + struct.pack(">I", len(data) + 8) + data)

        body = b"".join(chunks)
        with open(icns_path, "wb") as f:
            f.write(b"icns" + struct.pack(">I", len(body) + 8) + body)
        print(f"[OK] İkon üretildi: {icns_path}")
        return icns_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def build_app_bundle(base_dir: str, icns_path: Optional[str], arch: str) -> str:
    print(f"[2/5] PyInstaller ile '{APP_NAME}.app' ({arch}) derleniyor...")
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
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--target-arch",
        arch,
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

    if icns_path and os.path.exists(icns_path):
        cmd.extend(["--icon", icns_path, "--add-data", f"{icns_path}:assets"])

    png_path = os.path.join(base_dir, "assets", "app_icon.png")
    if os.path.exists(png_path):
        cmd.extend(["--add-data", f"{png_path}:assets"])

    glossaries_dir = os.path.join(base_dir, "glossaries")
    if os.path.isdir(glossaries_dir):
        cmd.extend(["--add-data", f"{glossaries_dir}:glossaries"])

    cmd.append(os.path.join(base_dir, "main.py"))
    env = os.environ.copy()
    pyi_cache = os.path.join(base_dir, "build", "pyinstaller_cache")
    os.makedirs(pyi_cache, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = pyi_cache
    subprocess.run(cmd, cwd=base_dir, env=env, check=True)

    app_path = os.path.join(base_dir, "dist", f"{APP_NAME}.app")
    if not os.path.isdir(app_path):
        raise RuntimeError(f"Beklenen .app paketi bulunamadı: {app_path}")
    return app_path


def update_info_plist(app_path: str, version: str) -> None:
    print("[3/5] Info.plist izin ve sürüm meta verileri güncelleniyor...")
    plist_path = os.path.join(app_path, "Contents", "Info.plist")
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    plist["CFBundleDisplayName"] = APP_NAME
    plist["CFBundleName"] = APP_NAME
    plist["CFBundleIdentifier"] = BUNDLE_ID
    plist["CFBundleShortVersionString"] = version
    plist["CFBundleVersion"] = version
    plist["LSMinimumSystemVersion"] = "12.0"
    plist["LSApplicationCategoryType"] = "public.app-category.utilities"
    plist["NSHighResolutionCapable"] = True
    plist["NSSupportsAutomaticGraphicsSwitching"] = True
    plist["NSScreenCaptureUsageDescription"] = (
        "SubVision AI, ekrandaki İngilizce altyazıları anlık okuyup Türkçeye "
        "çevirmek için Ekran Kaydı iznine ihtiyaç duyar."
    )
    plist["NSMicrophoneUsageDescription"] = (
        "SubVision AI, isteğe bağlı Canlı Ses (Whisper) modunda konuşmaları "
        "çevirmek için ses girişine ihtiyaç duyar."
    )

    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)


def codesign_app(app_path: str) -> None:
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "-").strip() or "-"
    mode_label = "Ad-hoc" if identity == "-" else f"Developer ID ({identity})"
    print(f"[4/5] '{os.path.basename(app_path)}' imzalanıyor ({mode_label})...")

    cmd = ["codesign", "--force", "--deep", "--sign", identity]
    if identity != "-":
        cmd.extend(["--options", "runtime", "--timestamp"])
    cmd.append(app_path)

    subprocess.run(cmd, check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", app_path], check=True)
    print("[OK] Kod imzası doğrulandı.")


def create_dmg(base_dir: str, app_path: str, version: str, arch: str) -> str:
    dmg_name = f"SubVisionAI-v{version}-macOS-{arch}.dmg"
    dmg_path = os.path.join(base_dir, "dist", dmg_name)
    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    print(f"[5/5] DMG kurulum paketi oluşturuluyor: {dmg_name} ...")
    staging = os.path.join(base_dir, "build", "dmg_staging")
    if os.path.exists(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)
    try:
        staged_app = os.path.join(staging, os.path.basename(app_path))
        shutil.copytree(app_path, staged_app, symlinks=True)
        os.symlink("/Applications", os.path.join(staging, "Applications"))

        guide_path = os.path.join(staging, "ILK_ACILIS_OKU.txt")
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write(FIRST_LAUNCH_GUIDE)

        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"{APP_NAME} v{version}",
                "-srcfolder",
                staging,
                "-ov",
                "-format",
                "UDZO",
                "-imagekey",
                "zlib-level=9",
                dmg_path,
            ],
            check=True,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    sha256 = hashlib.sha256()
    with open(dmg_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    digest = sha256.hexdigest()

    sums_path = os.path.join(base_dir, "dist", "SHA256SUMS-macOS.txt")
    with open(sums_path, "w", encoding="ascii") as f:
        f.write(f"{digest}  {dmg_name}\n")

    size_mb = os.path.getsize(dmg_path) / (1024 * 1024)
    print(f"[OK] DMG hazır: {dmg_path} ({size_mb:.1f} MB)")
    print(f"[OK] SHA-256:  {digest}")
    return dmg_path


def main() -> int:
    if sys.platform != "darwin":
        print("[HATA] build_macos.py yalnızca macOS üzerinde çalıştırılabilir.")
        return 1

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="Build SubVision AI macOS .app and .dmg")
    parser.add_argument(
        "--version",
        default=read_project_version(base_dir),
        help="Sürüm numarası (varsayılan: pyproject.toml'dan okunur)",
    )
    parser.add_argument(
        "--arch",
        default="arm64",
        choices=["arm64", "x86_64", "universal2"],
        help="Hedef mimari (varsayılan: arm64)",
    )
    parser.add_argument(
        "--skip-dmg",
        action="store_true",
        help="Yalnızca .app paketini üret, .dmg oluşturma",
    )
    args = parser.parse_args()
    version = args.version.lstrip("v")

    icns_path = ensure_icns_icon(base_dir)
    app_path = build_app_bundle(base_dir, icns_path, args.arch)
    update_info_plist(app_path, version)
    codesign_app(app_path)

    if not args.skip_dmg:
        create_dmg(base_dir, app_path, version, args.arch)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
