# Contributing to SubVision AI

Thank you for considering contributing to **SubVision AI**! Every contribution — bug reports, game compatibility entries, glossary improvements, performance optimizations, or new features — helps make real-time offline English-to-Turkish subtitle translation better for everyone.

## Ways to Contribute

1. **Report Bugs & Edge Cases:** Open an issue using the Bug Report template (include OS, CPU, game/app name, and OCR mode).
2. **Add Game / Platform Compatibility Entries:** Tested SubVision AI on a game or video player? Open a PR updating [COMPATIBILITY.md](COMPATIBILITY.md).
3. **Improve Glossary & Slang Normalization:** Add common game/movie phrases or OCR noise fixes to `glossary.py` with corresponding unit tests in `test_pipeline.py`.
4. **Code & Architecture Improvements:** Help improve OCR accuracy, context-aware translation backends (`subvision/context_translator.py`), live audio transcription (`subvision/audio_whisper.py`), or UI/UX (`subvision/ui_widgets.py`, `main.py`).

## Development Setup

```bash
git clone https://github.com/Andacbasaran/subvision-ai-subtitle-translator.git
cd subvision-ai-subtitle-translator
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install ruff
```

### Optional Live Audio Dependencies (Whisper)

```bash
# Cross-platform (microphone / loopback device)
pip install -e ".[audio]"

# Windows WASAPI loopback (recommended for desktop/game audio)
pip install -e ".[audio-windows]"
```

## Running Tests & Linter

Before opening a Pull Request, please verify all checks pass:

```bash
# Syntax check
python -m py_compile hardware.py glossary.py translator.py ocr_engine.py overlay_ui.py main.py benchmark.py build_exe.py test_pipeline.py
python -m py_compile subvision/*.py

# Linter
ruff check subvision/

# Automated test suite (headless Qt supported)
QT_QPA_PLATFORM=offscreen python -m unittest test_pipeline -v
```

## Pull Request Guidelines

- Keep PRs focused on a single feature, bugfix, or documentation improvement.
- Preserve **100% offline default behavior** (CTranslate2 INT8 on CPU, 0 MB VRAM) — optional cloud/audio features must remain opt-in with graceful fallback.
- Add or update unit tests in `test_pipeline.py` for any new logic.
- Follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
