# Changelog

All notable changes to **SubVision AI** are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.6.0] — 2026-11-23

### Added
- **Multi-Language Pack Manager (`subvision/language_packs.py`):** Added pluggable offline CTranslate2 / OPUS-MT language packs supporting `en-tr`, `en-es`, `en-de`, `en-fr`, `en-pt`, `en-ru`, `en-it`, and `ja-en` with on-demand download and switching directly from Settings.
- **Apple Silicon MPS Acceleration with CPU Fallback:** Added optional Metal Performance Shaders (MPS) GPU acceleration on macOS Apple Silicon (M1–M4) with automatic, crash-free fallback to CPU INT8/FP32 inference.
- **Community Glossary Hub & 6 New Game Packs (`subvision/glossary_hub.py`, `glossaries/`):** Added an in-app Community Glossary Hub to browse and sync term packs alongside 6 new bundled game glossaries (`elden_ring.json`, `rdr2.json`, `witcher3.json`, `skyrim.json`, `starfield.json`, `persona5.json`), expanding the built-in library to 9 games.
- **Vocabulary Notebook & Rich HTML Anki `.tsv` Export (`subvision/vocab_learner.py`, `subvision/exporters.py`):** Save notable dialogue terms and idioms while playing or watching into a personal Vocabulary Notebook and export styled, rich-HTML Anki `.tsv` flashcard decks in one click.
- **Linux & Steam Deck (SteamOS) Packaging & Guide (`scripts/build_linux.py`, `docs/STEAM_DECK_GUIDE.md`):** Added native Linux x64 `.tar.gz` bundle packaging, SteamOS / Steam Deck Gaming Mode setup guide, and a Homebrew Cask formula (`packaging/homebrew/subvision-ai.rb`) for macOS Apple Silicon.
- **SEO & Interactive TR/EN Official Website (`website/`):** Upgraded `subvisionai.andacbasaran.com` with Cloudflare Worker SSR meta/hreflang localization (`/tr`, `/en`), interactive live subtitle simulator, Studio 2.0 hotspot tour, and automatic latest-release download routing for Windows `.exe`, macOS `.dmg`, and Linux `.tar.gz`.

### Changed
- **Modular Repository Reorganization:** Consolidated core modules into `subvision/`, moved build and launcher scripts into `scripts/`, moved unit tests into `tests/`, relocated the Inno Setup script to `packaging/inno/installer.iss`, and stopped tracking the compiled `SubVisionAI.exe` binary in git.
- **Unified 3-Platform CI/CD & Release Pipeline:** Added `.github/workflows/ci.yml` (Ruff lint + Windows/Linux/macOS Python 3.11 test matrix), unified `.github/workflows/release.yml` to publish Windows, macOS, and Linux assets together with a single `SHA256SUMS.txt` and download table, added `.github/release.yml` release note categories, and updated Winget, Scoop, and Homebrew manifests to `1.6.0`.

## [1.5.0] — 2026-11-23

### Added
- **Studio 2.0 Redesign & Cinema Frame Brand Identity:** Redesigned the desktop application, overlay HUD, C# online installer wizard, and landing page around a flat **Studio Graphite** palette with a left-sidebar navigation architecture, new **Cinema Frame** vector logo (`assets/app_icon.svg`, `.ico`, `.png`, `.icns`), and refreshed UI preview screenshots.
- **Dynamic Tight-Hugging Subtitle Overlay:** Added ROI-normalized OCR bounding-box tracking with tight subtitle backdrops and controlled box expansion when Turkish translations overflow the original English line width.
- **Target Application / Window Capture Lock (`subvision/window_tracker.py`):** Lock translation capture to a specific game or media window with automatic Alt+Tab pause and overlay-hide protection.
- **macOS Apple Silicon (`arm64`) Native DMG Release:** Added `build_macos.py`, macOS `.app` bundle & DMG packaging, and native Cocoa overlay & Retina HiDPI ROI coordinate support.
- **Cross-Platform GitHub Releases Auto-Updater (`subvision/updater.py`):** Upgraded the in-app updater to detect, download, and launch platform-appropriate Windows and macOS releases directly from GitHub Releases.
- **Expanded Unit Test Coverage:** Added automated tests covering `QFont` safety, tight-hugging overlay layout, OCR bounding-box outlier filtering, and Alt+Tab focus gating.

### Fixed
- **PyQt6 Crash & Stability Fixes:** Fixed `QFont` float `pointSize` crash in `ROISelectorOverlay`, missing `QCheckBox` import, Windows `F7`/`F8` hotkey double-triggering, `QPainter` lifecycle safety, and `QThread` shutdown cleanup.
- **Packaging & CI Fixes:** Stripped duplicate UTF-8 BOM from `installer.iss` and updated the macOS release runner to `macos-latest`.

## [1.4.0] — 2026-11-22

### Added
- **Modular Package Architecture (`subvision/`):** Extracted background workers (`subvision/workers.py`), reusable HiDPI widgets (`subvision/ui_widgets.py`), internationalization (`subvision/i18n.py`), update checker (`subvision/updater.py`), context-aware translation layer (`subvision/context_translator.py`), and live audio transcription (`subvision/audio_whisper.py`) while keeping `main.py` 100% backwards-compatible.
- **Optional Context-Aware Translation Layer:** Added pluggable EN → TR context backends (local **Ollama**, **Google Gemini**, **DeepL**, and **OpenAI-compatible** endpoints) passing the last 3 dialogue turns for pronoun/tone consistency, with automatic instant fallback to 100% offline CTranslate2 INT8 on timeout or error.
- **Optional Live Audio Subtitle Mode (Whisper):** Added WASAPI loopback (`pyaudiowpatch`) & microphone (`sounddevice`) live English speech transcription powered by `faster-whisper` (CTranslate2 INT8 CPU) with lightweight RMS VAD segmentation (`SpeechSegmenter`).
- **In-App Update Checker:** Asynchronous GitHub Releases version checker with startup toggle and one-click release link.
- **Per-App / Game Profiles & Multi-ROI (`subvision/profiles.py`):** Save and switch named ROI/OCR/color/glossary profiles, with optional automatic Windows foreground `.exe` matching.
- **External JSON Custom Glossaries (`subvision/custom_glossary.py`, `glossaries/`):** Drop-in game/show JSON packs (`spiderman2.json`, `cyberpunk2077.json`, `baldurs_gate3.json`) supporting instant exact overrides, `do_not_translate` lore name protection, and custom term replacements.
- **Customizable Global Hotkeys (F1–F12) & System Tray:** Rebind ROI / Toggle / Sample hotkeys in Settings to avoid game collisions (e.g. `F9` quickload) and minimize smoothly to the System Tray.
- **Dialogue History Exporters (`subvision/exporters.py`):** One-click `.srt` subtitle and Anki-compatible `.csv` flashcard export directly from the History tab.
- **EN / TR Interface Language Selector (i18n):** Added English and Turkish UI language switching in Settings, plus global English `README.md` alongside `README.tr.md`.
- **CI/CD & Open-Source Ecosystem:** Added `pyproject.toml`, cross-platform PR CI workflow (`.github/workflows/ci.yml` with Ruff + Windows/Linux/macOS test matrix), `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `COMPATIBILITY.md`, GitHub Issue/PR templates, Winget & Scoop manifests, and SignPath.io signing guide.

## [1.3.0] — 2026-11-21

### Added
- Streamlined 3-tab **SubVision AI Studio v1.3** UI (`Ana Ekran`, `Geçmiş`, `Ayarlar`).
- Anti-Phantom game mask filter & colored speaker name recognition (`Miles:`, `Peter:`) + single-word subtitle capture (`"Wait!"`, `"No!"`).
- Auto-Fit `QFontMetrics` dynamic font sizing on click-through overlay.
- SHA-256 Authenticode signed installer (`SubVisionAI.exe`) with automatic `SubVisionAI-Uninstaller.exe` and optional component retention.
- Official website (`subvisionai.andacbasaran.com`) and Cloudflare Worker distribution.

## [1.2.0] — 2026-11-19

### Added
- Asynchronous **Latest-Frame-Wins** pipeline (`LatestTextSlot`) eliminating subtitle queue lag (~88 ms end-to-end).
- Universal CPU / ISA detection (`hardware.py`) with automatic compute-type fallback (`INT8` → `INT8_FLOAT32` → `INT16` → `FLOAT32`).
- Built-in hardware benchmark suite (`benchmark.py`) and 22 automated pipeline tests (`test_pipeline.py`).
