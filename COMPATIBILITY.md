# Game & Platform Compatibility Matrix

SubVision AI works with any application displaying on-screen English subtitles (or English audio via the optional Whisper mode).

> 💡 **Tested a game or player not listed here?** Feel free to open a **Compatibility Report** issue or submit a Pull Request adding it to the tables below!

## PC Games

> **Tip:** Always set games to **Borderless Windowed** mode so the click-through Turkish overlay can render cleanly on top without interrupting gameplay.

| Game | Display Mode | Recommended OCR Mode | Overlay Mode | Status | Notes |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Marvel's Spider-Man 2** | Borderless Windowed | `fast_mask` | `cover` (Auto-Fit) | ✅ Verified | Colored speaker names (`Miles:`, `Peter:`) over bright skies handled natively. |
| **Red Dead Redemption 2** | Borderless Windowed | `fast_mask` | `cover` (Auto-Fit) | ✅ Verified | Enable subtitle background or default white outlined text. |
| **Baldur's Gate 3** | Borderless Windowed | `fast_mask` / `hybrid` | `cover` | ✅ Verified | Great with optional Context-Aware mode for long RPG dialogues. |
| **Cyberpunk 2077** | Borderless Windowed | `fast_mask` | `cover` | ✅ Verified | Works smoothly with yellow/white subtitle styles. |
| **The Witcher 3** | Borderless Windowed | `fast_mask` | `cover` | ✅ Verified | Standard bottom subtitle area. |
| **Visual Novels / Light-BG RPGs** | Windowed / Borderless | `hybrid` or `full_ocr` | `cover` / `above` | ✅ Verified | Use `hybrid` or `full_ocr` when dark text appears on light dialogue boxes. |

## Streaming & Video Players

| Platform / Player | Recommended OCR Mode | Overlay Mode | Status | Notes |
| :--- | :--- | :--- | :---: | :--- |
| **YouTube (Chrome / Edge / Firefox)** | `fast_mask` | `cover` | ✅ Verified | Works with CC subtitles and hardcoded English subtitles. |
| **VLC Media Player** | `fast_mask` | `cover` | ✅ Verified | Zero DRM restrictions, ultra-low latency. |
| **Twitch / Live Streams** | `fast_mask` or **Live Audio (Whisper)** | `above` / `cover` | ✅ Verified | Use Live Audio (Whisper) mode when streamers have no English captions. |
| **Netflix / Prime Video / Disney+ (Browser)** | `fast_mask` | `cover` | ⚠️ Browser Note | Disable browser Hardware Acceleration if DRM causes black capture frames. |
| **Udemy / Coursera / Educational Videos** | `fast_mask` / `hybrid` | `cover` | ✅ Verified | Enable **Bilingual Mode** to see English + Turkish side-by-side. |

## Operating Systems

| OS | Status | Notes |
| :--- | :---: | :--- |
| **Windows 10 (2004+) & Windows 11 (x64)** | ✅ Full Support | Full `WDA_EXCLUDEFROMCAPTURE` support for direct `cover` mode + Global `F7/F8/F9` hotkeys. |
| **Linux (X11 / Wayland)** | ✅ Supported | Launch via `./start.sh`. Uses `above` overlay placement when capture-exclude is unavailable. |
| **macOS (Intel & Apple Silicon M1–M4)** | ✅ Supported | Launch via `./start.sh`. Grant Screen Recording permission when prompted. |
