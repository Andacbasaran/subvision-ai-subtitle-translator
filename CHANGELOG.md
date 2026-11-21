# Changelog

All notable changes to **SubVision AI** are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

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
