<div align="center">

<img src="assets/app_icon.png" alt="SubVision AI Logo" width="96" height="96" />

# ⚡ SubVision AI — Real-Time On-Screen & Live-Audio Subtitle Studio (EN ➔ TR)

**🇬🇧 English (Active)** · **🇹🇷 [Türkçe README](README.tr.md)** · **[🎮 Compatibility Matrix](COMPATIBILITY.md)** · **[🤝 Contributing](CONTRIBUTING.md)** · **[🛡️ Security](SECURITY.md)**

**Ultra-low-latency (~88 ms), 100% offline, 0 MB VRAM real-time English-to-Turkish subtitle translator for PC games, movies, TV shows, and live streams.**

[![Website](https://img.shields.io/badge/🌐_Official_Website-subvisionai.andacbasaran.com-0EA5E9?style=for-the-badge)](https://subvisionai.andacbasaran.com/)
[![Direct Download](https://img.shields.io/badge/⬇️_Download_Now-SubVisionAI.exe_(v1.4.0)-2563EB?style=for-the-badge&logo=windows&logoColor=white)](https://subvisionai.andacbasaran.com/downloads/SubVisionAI.exe)
[![GitHub Releases](https://img.shields.io/badge/📦_All_Packages-Setup_%26_Portable_ZIP-1D4ED8?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/latest)

[![CI](https://github.com/Andacbasaran/subvision-ai-subtitle-translator/actions/workflows/ci.yml/badge.svg)](https://github.com/Andacbasaran/subvision-ai-subtitle-translator/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/UI-PyQt6_Studio_v1.4-41CD52?style=flat-square&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![CTranslate2](https://img.shields.io/badge/NMT-CTranslate2_INT8-FACC15?style=flat-square)](https://github.com/OpenNMT/CTranslate2)
[![RapidOCR](https://img.shields.io/badge/OCR-RapidOCR_ONNX-38BDF8?style=flat-square)](https://github.com/RapidAI/RapidOCR)
[![VRAM](https://img.shields.io/badge/GPU_/_VRAM-0_MB_(100%25_CPU)-10B981?style=flat-square)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-A78BFA?style=flat-square)](LICENSE)

</div>

---

## ✨ Why SubVision AI? (What's New in v1.4)

**SubVision AI** reads English subtitles in real time from any **PC Game** *(Spider-Man 2, RDR2, Baldur's Gate 3, Cyberpunk 2077)*, **Streaming / Video Player** *(Netflix, Prime Video, VLC, YouTube)*, or **Live Stream** *(Twitch, Udemy)* and renders natural Turkish translations onto a transparent, **click-through overlay** directly over the original text — **100% offline on CPU with 0 MB VRAM**.

<table>
  <tr>
    <td width="50%">
      <b>⚡ Async Latest-Frame-Wins Pipeline (~88 ms)</b><br/>
      OCR (<code>~20 ms</code>) and CTranslate2 INT8 NMT (<code>~68 ms</code>) run in decoupled threads. Fast dialogues never queue up; the latest on-screen line always wins. Static scenes sleep at <code>0.18 ms</code> (<code>0.2% CPU</code>).
    </td>
    <td width="50%">
      <b>🧠 Optional Context-Aware Translation Layer (v1.4)</b><br/>
      Keep <b>100% offline CTranslate2 INT8</b> as the default, or optionally enable sliding-window dialogue context (last 3 turns) via local <b>Ollama</b>, <b>Gemini</b>, <b>DeepL</b>, or any <b>OpenAI-compatible</b> endpoint — with instant automatic fallback to local CT2.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>🎙️ Optional Live Audio Mode — Whisper (v1.4)</b><br/>
      Watching an unsubtitled Twitch stream or YouTube video? Enable optional <b>faster-whisper</b> (INT8 CPU) + WASAPI loopback / mic capture to transcribe English speech directly into live Turkish subtitles.
    </td>
    <td width="50%">
      <b>🎯 Anti-Phantom Game Mask & Auto-Fit Overlay</b><br/>
      Filters bright skies and game HUD noise without phantom words, captures colored speaker names (<code>Miles:</code>, <code>Peter:</code>) and single-word lines (<code>"Wait!"</code>), and auto-fits Turkish text over the original subtitle via <code>WDA_EXCLUDEFROMCAPTURE</code>.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>🌐 Bilingual UI (EN / TR) & Update Checker (v1.4)</b><br/>
      Switch interface language between English and Turkish right in Settings, with an optional non-blocking GitHub Releases update checker.
    </td>
    <td width="50%">
      <b>🧩 Modular Open-Source Architecture (v1.4)</b><br/>
      Clean <code>subvision/</code> package layout, cross-platform CI (Windows/Linux/macOS), Winget & Scoop manifests, and SHA-256 Authenticode signed Windows releases.
    </td>
  </tr>
</table>

---

## 🖥️ Application Interface

<div align="center">
  <img src="assets/ui_preview.png" alt="SubVision AI Studio — Home Screen" width="880" />
</div>

---

## 🎮 2-Key Workflow & Global Hotkeys

1. Open your game in **Borderless Windowed** mode (or open any video player / browser).
2. Press **`F7`** and drag a box around the English subtitle region.
3. Press **`F8`** to start live Turkish translation. Mouse clicks pass straight through the overlay to your game or player.

| Global Hotkey | Action | Description |
| :---: | :--- | :--- |
| **`F7`** | 🎯 **Select Subtitle Region** | Opens the multi-monitor 4K DPI region selector (`ROI`). |
| **`F8`** | ▶️ **Start / Stop** | Toggles real-time OCR or Live Audio translation. |
| **`F9`** | 🧪 **Try Sample Scene** | Tests overlay appearance and translation latency with sample dialogue. |
| **`ESC`** | ❌ **Cancel Selection** | Cancels region selection mode. |

---

## 🚀 Installation

### Windows (Recommended)
- **Signed Installer / Setup Wizard:** Download [SubVisionAI.exe](https://subvisionai.andacbasaran.com/downloads/SubVisionAI.exe) or grab the **Inno Setup `.exe`** / **Portable `.zip`** from [GitHub Releases](https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/latest).
- **Winget & Scoop Manifests:** Ready-to-submit manifests are available under [`packaging/winget/`](packaging/winget/) and [`packaging/scoop/`](packaging/scoop/).

### Linux & macOS (Intel / Apple Silicon M1–M4)
```bash
git clone https://github.com/Andacbasaran/subvision-ai-subtitle-translator.git
cd subvision-ai-subtitle-translator
./start.sh
```

### Developer Setup (From Source)
```bash
git clone https://github.com/Andacbasaran/subvision-ai-subtitle-translator.git
cd subvision-ai-subtitle-translator
python -m venv .venv
# Windows: .\.venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

#### Optional: Enable Live Audio Mode (Whisper)
```bash
# Cross-platform (microphone / loopback)
pip install -e ".[audio]"

# Windows WASAPI desktop audio loopback
pip install -e ".[audio-windows]"
```

---

## 📊 Performance Benchmarks

<div align="center">
  <img src="assets/benchmark_chart.png" alt="SubVision AI Performance Benchmark Chart" width="960" />
</div>

| Pipeline Stage | Average Latency | Notes |
| :--- | :---: | :--- |
| **1. Frame Diff Lock (Idle Skip)** | **`0.18 ms`** | Skips unchanged frames at `0.2% CPU` |
| **2. Adaptive Mask + Fast Line OCR (1 Line)** | **`19.83 ms`** | Direct CRNN batching without heavy DBNet |
| **3. CTranslate2 INT8 NMT (Short Line)** | **`68.03 ms`** | `opus-mt-tc-big-en-tr` INT8, `0 MB VRAM` |
| **4. Zero-Wait LRU Cache & Glossary** | **`0.0045 ms`** | Instant hit without touching NMT thread |

Run the benchmark locally via `python benchmark.py` or execute the automated test suite:
```bash
QT_QPA_PLATFORM=offscreen python -m unittest test_pipeline -v
```

---

## 📂 Project Structure

```text
├── main.py                              # PyQt6 Studio entry point & MainWindow
├── subvision/                           # Modular core package (v1.4+)
│   ├── context_translator.py            # Optional context-aware layer (Ollama/Gemini/DeepL/OpenAI) + CT2 fallback
│   ├── audio_whisper.py                 # Optional live audio capture (WASAPI/sounddevice) + faster-whisper VAD
│   ├── workers.py                       # Async Latest-Frame-Wins CaptureTranslateWorker, ModelLoader, BenchmarkWorker
│   ├── ui_widgets.py                    # Reusable HiDPI PyQt6 widgets & vector icon builders
│   ├── updater.py                       # Async GitHub Releases SemVer update checker
│   └── i18n.py                          # Lightweight EN / TR interface localization
├── ocr_engine.py                        # MSS regional capture, adaptive color mask, anti-phantom RapidOCR
├── translator.py                        # 100% offline CTranslate2 (INT8/FP32) EN -> TR engine + LRU Cache
├── glossary.py                          # OCR cleanup, anti-gibberish plausibility filter, speaker parser, glossary
├── overlay_ui.py                        # Auto-Fit click-through overlay & multi-monitor 4K DPI ROI selector
├── hardware.py                          # Universal CPU/ISA detection & adaptive runtime tuning
├── test_pipeline.py                     # Automated unit & integration test suite
├── packaging/                           # Winget, Scoop, and SignPath.io distribution configs
└── .github/workflows/                   # Cross-platform PR CI (ci.yml) & Windows Release (release-windows.yml)
```

---

## 🤝 Contributing & License

Contributions are warmly welcome! Read [CONTRIBUTING.md](CONTRIBUTING.md), check [COMPATIBILITY.md](COMPATIBILITY.md) to add tested games/players, and review [SECURITY.md](SECURITY.md) for privacy & binary verification details.

Licensed under the **[MIT License](LICENSE)**.
