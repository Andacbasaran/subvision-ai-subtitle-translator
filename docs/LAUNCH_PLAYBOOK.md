# 🚀 SubVision AI v1.5.0 — Büyüme, Vitrin & Lansman Oyun Kitabı (Launch Playbook)

Bu rehber, **SubVision AI v1.5.0** sürümünün GitHub yıldızlarını, indirme sayılarını ve topluluk görünürlüğünü hızlandırmak için hazırlanmış **uygulanabilir, kopyala-yapıştır lansman rehberidir**.

---

## 1. GitHub SEO & Vitrin Kontrol Listesi

GitHub deposu ana sayfasının sağ üstündeki **About (⚙️)** panelinden aşağıdaki ayarları eksiksiz girin:

### 📌 Repo Description (≤ 160 Karakter)
```text
Real-time (~88ms), 100% offline, 0 MB VRAM subtitle translator for PC games, movies & streams (EN→TR). Native Windows x64 & macOS Apple Silicon.
```

### 🌐 Website URL
```text
https://subvisionai.andacbasaran.com
```

### 🏷️ 12 Seçilmiş GitHub Topic
Aşağıdaki 12 etiketi tek tek ekleyin (arama hacmi + niş keşif dengesi için seçilmiştir):
```text
subtitle-translator
ocr
ctranslate2
real-time-translation
gaming-overlay
offline-ai
pyqt6
whisper
macos
windows
turkish
open-source
```

### 🖼️ Social Preview Görseli (`1280 × 640 px`) Tasarım Brief'i
*Settings ➔ General ➔ Social preview* bölümüne yüklenecek OG kartı için önerilen kompozisyon:
- **Arka Plan:** `#0C0C0E` düz koyu zemin + ince mimari nokta ızgarası (`website/index.html` ile birebir uyumlu).
- **Sol Blok (%45):**
  - Üstte Cinema Frame logosu (`assets/app_icon.png`) + **SubVision AI `v1.5`**
  - Büyük başlık (`Inter ExtraBold`, `#FAFAFA`): *"Any on-screen subtitle."* / İkinci satır (`#F59E0B`): *"Translated in ~88 ms."*
  - Alt rozetler: `0 MB VRAM` · `100% Offline` · `Windows & macOS` · `MIT`
- **Sağ Blok (%55):**
  - Hafif perspektifli veya temiz çerçeveli oyun sahnesi üzerinde sıkı hizalanmış Türkçe altyazı örneği + altında `assets/ui_preview.png` önizleme kartı.
- **Güvenli Alan:** Kenarlardan en az `64 px` boşluk bırakın (X/Reddit/Discord kırpmalarına karşı).

### 💬 GitHub Discussions Kurulumu
*Settings ➔ Features ➔ Discussions* seçeneğini açın ve şu 4 kategoriyi oluşturun:
1. **🎮 Game Compatibility** — Kullanıcıların test ettiği oyunları ve önerilen ROI / maske ayarlarını paylaşması için.
2. **📖 Community Glossaries** — RPG/JRPG oyunları için `.json` terim sözlüğü paylaşımları için.
3. **🌍 Language Requests** — `EN ➔ ES / DE / PT / JA` gibi yeni dil çiftleri için oy toplama alanı (küresel yıldız mıknatısı).
4. **✨ Show & Tell** — Kullanıcıların kendi ekran görüntüleri ve kurulumları için.

---

## 2. 15 Saniyelik Demo GIF & Video Çekim Reçetesi (`assets/demo.gif`)

Bir GitHub projesinde **ilk 5 saniyede yıldız aldıran en güçlü öğe** gerçek zamanlı çalışan bir demo GIF'idir.

### 🎬 Sahne & Kayıt Kurulumu
1. **Oyun / Video Seçimi:** Yüksek kontrastlı, 12–15 saniye içinde 2–3 net diyalog repliği geçen bir sahne seçin:
   - *Önerilen:* **Spider-Man 2**, **Cyberpunk 2077**, **Red Dead Redemption 2** veya 1080p sinematik bir oyun fragmanı (YouTube/VLC).
2. **Overlay Ayarları (SubVision Studio 2.0):**
   - **Sıkı Dinamik Hizalama:** Açık (orijinal altyazıyı temizce kapatsın).
   - **Çift Dilli Mod (Bilingual):** İsteğe bağlı — ilk 7 saniye tek dil Türkçe, sonraki 7 saniye çift dilli göstermek *ya da* doğrudan temiz Türkçe göstermek en yüksek etkiyi verir.
   - **Renk & Arka Plan:** Yüksek kontrastlı `#FAFAFA` veya `#F59E0B` metin, `%85` koyu arka plan.
3. **Kayıt:** OBS Studio (Windows) veya QuickTime / `⌘+⇧+5` (macOS) ile **1920×1080 @ 30 FPS** veya yalnızca alt-orta 1280×720 bölgeyi **12–15 saniye** kaydedin (`raw_demo.mp4`).

### 🛠️ `ffmpeg` ile < 5 MB Kristal Netliğinde `assets/demo.gif` Üretme
2 aşamalı palet üretimi (`palettegen` + `paletteuse`) renk şeritlenmesini önler ve dosya boyutunu küçük tutar:

```bash
# 1. En iyi renk paletini üret (900px genişlik, 14 FPS — GitHub README için ideal)
ffmpeg -y -i raw_demo.mp4 \
  -vf "fps=14,scale=900:-1:flags=lanczos,palettegen=stats_mode=diff" \
  palette.png

# 2. Paleti uygulayarak < 5 MB optimize GIF oluştur
ffmpeg -y -i raw_demo.mp4 -i palette.png \
  -lavfi "fps=14,scale=900:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle" \
  assets/demo.gif

# Boyut 5 MB'ı aşarsa fps=12 veya scale=800:-1 ile tekrarlayın
ls -lh assets/demo.gif
```

> **Sosyal Medya (X / Reddit) İçin MP4 Varyantı:** GIF yerine doğrudan MP4 yüklemek çok daha keskin görünür:
```bash
ffmpeg -y -i raw_demo.mp4 -vf "scale=1280:-2" -c:v libx264 -crf 20 -pix_fmt yuv420p -movflags +faststart demo_social.mp4
```

### 📌 README'ye Ekleme
`assets/demo.gif` dosyasını repoya ekledikten sonra `README.md` ve `README.tr.md` içindeki `<!-- Demo GIF slot ... -->` yorum bloğunu açmanız yeterlidir.

---

## 3. Yayına Hazır Lansman Metinleri (Kopyala-Yapıştır)

### 1️⃣ Technopat Sosyal / DonanımHaber (TR)
**Başlık:**
> [Açık Kaynak / Ücretsiz] Oyunlar ve Diziler İçin %100 Çevrimdışı, 0 MB VRAM Anlık Türkçe Altyazı Çevirici — SubVision AI v1.5 (Windows & macOS)

**İçerik:**
```markdown
Merhaba arkadaşlar,

Türkçe yaması olmayan PC oyunları (Spider-Man 2, RDR2, Baldur's Gate 3, Cyberpunk vb.), diziler ve canlı yayınlar için geliştirdiğim açık kaynak kodlu **SubVision AI** projesinin **v1.5.0** sürümünü paylaşmak istiyorum.

**Nasıl çalışıyor?**
Ekrandaki İngilizce altyazı bölgesini `F7` ile seçiyorsunuz, `F8` ile başlatıyorsunuz. Program ekrandaki altyazıyı ~20 ms içinde okuyup ~68 ms içinde Türkçeye çeviriyor (toplam ~88 ms) ve orijinal altyazının tam üzerine şeffaf, fare tıklamalarını arkaya geçiren (click-through) bir katman olarak oturtuyor.

**Öne çıkan teknik özellikler (v1.5.0):**
- **0 MB VRAM (%100 CPU):** Ekran kartı belleğine hiç dokunmaz, oyunlarda FPS kaybı yaratmaz. Altyazı sabit dururken 0.18 ms kare kilidiyle %0.2 CPU kullanır.
- **%100 Çevrimdışı & Ücretsiz (MIT):** İlk açılışta 227 MB'lık CTranslate2 INT8 modelini indirir; sonrasında internet, API anahtarı veya abonelik istemez.
- **Sıkı Dinamik Hizalama & Alt+Tab Kilidi:** Orijinal altyazı boyutunu ölçüp kutudan taşmadan tam üzerine oturur; Alt+Tab yaptığınızda otomatik gizlenir.
- **Opsiyonel Bağlam LLM & Canlı Ses (Whisper):** Dilerseniz Ollama / Gemini / DeepL bağlayabilir veya altyazısız Twitch/YouTube yayınları için canlı ses (Whisper) modunu açabilirsiniz.
- **Windows x64 & macOS Apple Silicon (M1–M4):** Windows'ta SHA-256 imzalı `.exe` / Portable `.zip`, macOS'ta yerel `.dmg` olarak hazır.

🌐 Web Sitesi: https://subvisionai.andacbasaran.com
💻 GitHub (Kaynak Kod & Sürümler): https://github.com/Andacbasaran/subvision-ai-subtitle-translator

Denediğiniz oyunlardaki performans ve geri bildirimlerinizi bekliyorum!
```

---

### 2️⃣ r/veYakinEvren & r/GeymingTR (TR)
**Başlık:**
> Türkçe yaması olmayan oyunlar için %100 çevrimdışı, FPS düşürmeyen anlık ekran üstü altyazı çevirici yaptım (SubVision AI v1.5 — Ücretsiz & Açık Kaynak)

**İçerik:**
```markdown
Selamlar,

Türkçe desteği olmayan oyunları oynarken sürekli yama aramak ya da ekranda takılan, reklamlı/ücretli çeviri araçlarıyla uğraşmak yerine kendi bilgisayarınızda %100 çevrimdışı çalışan **SubVision AI**'ı geliştirdim. Az önce **v1.5.0** sürümünü yayınladım.

- Oyun içinde **`F7`** ile altyazı alanını çiziyorsunuz, **`F8`** ile çeviri başlıyor.
- **0 MB VRAM** kullanıyor (tamamen CPU'da CTranslate2 INT8 ile çalışıyor), yani GPU'yu yormuyor ve FPS düşürmüyor.
- Ortalama **~88 ms** gecikmeyle anlık çeviriyor, orijinal İngilizce altyazının tam üstünü temizce kapatıyor.
- **Alt+Tab** yaptığınızda pencere kilidi sayesinde altyazı otomatik gizleniyor.
- Oyunlara özel JSON terim sözlükleri (`Spider-Man 2`, `BG3`, `Cyberpunk 2077` hazır geliyor), SRT/Anki dışa aktarım ve isterseniz Ollama/Gemini bağlam modu da var.
- Hem **Windows x64** hem **macOS Apple Silicon (M1–M4)** destekli, tamamen ücretsiz ve MIT lisanslı açık kaynak.

İndirme & canlı önizleme: https://subvisionai.andacbasaran.com
GitHub: https://github.com/Andacbasaran/subvision-ai-subtitle-translator

Hangi oyunlarda denediniz, neleri geliştirelim? Yorumlarda yazabilirsiniz!
```

---

### 3️⃣ X (Twitter) — Thread & Tek Tweet (TR + EN)

**🇹🇷 Tek Tweet (Kısa & Vurucu — `demo_social.mp4` ile paylaşın):**
```text
Türkçe yaması olmayan oyunlar ve diziler için %100 çevrimdışı, 0 MB VRAM tüketen anlık altyazı çevirici: SubVision AI v1.5 yayında ⚡

• F7 ile alanı seç, F8 ile başlat (~88 ms gecikme)
• Sıkı hizalama + Alt+Tab pencere kilidi
• Opsiyonel Ollama/Gemini bağlam & Whisper canlı ses
• Windows x64 + macOS Apple Silicon (.dmg)
• %100 ücretsiz & açık kaynak (MIT)

İndir: https://subvisionai.andacbasaran.com
GitHub: https://github.com/Andacbasaran/subvision-ai-subtitle-translator
```

**🇬🇧 English Thread (2 Tweets — `demo_social.mp4` ile paylaşın):**
```text
1/ Just shipped SubVision AI v1.5 — a 100% offline, 0 MB VRAM real-time on-screen subtitle translator for PC games, movies & live streams ⚡

• ~88 ms end-to-end on CPU (RapidOCR + CTranslate2 INT8)
• Tight-hugging click-through overlay + Alt+Tab window lock
• Native Windows x64 (.exe) & macOS Apple Silicon (.dmg)
• Free & MIT open source

🔗 https://github.com/Andacbasaran/subvision-ai-subtitle-translator

2/ Built for zero FPS drop in games:
- 0.18 ms frame-diff lock sleeps at 0.2% CPU on static subtitles
- Async Latest-Frame-Wins pipeline (fast dialogue never queues up)
- Optional 3-turn context layer via local Ollama / Gemini / DeepL
- Optional faster-whisper live audio mode + SRT / Anki export

Would love feedback — and contributions for more target languages (ES/DE/PT/JA)!
```

---

### 4️⃣ r/LocalLLaMA & r/opensource (EN)
**Başlık:**
> SubVision AI v1.5: ~88ms, 100% offline, 0 MB VRAM real-time subtitle translator for games & video (CTranslate2 INT8 + optional Ollama context layer, Windows & macOS)

**İçerik:**
```markdown
Hi everyone,

I just released **v1.5.0** of **SubVision AI**, an open-source (MIT) real-time on-screen and live-audio subtitle translator built to run alongside demanding games without touching your GPU.

**Why CPU-only / 0 MB VRAM?**
When you're playing a modern game, any translator that loads PyTorch onto VRAM steals precious memory and causes frame pacing hitches. SubVision AI runs an async **Latest-Frame-Wins** pipeline entirely on CPU:
- **Frame Diff Lock (`0.18 ms`):** Skips unchanged frames at ~0.2% CPU.
- **Fast Line RapidOCR (`~20 ms`):** Adaptive color/contrast mask + direct CRNN batching without heavy DBNet overhead.
- **CTranslate2 INT8 NMT (`~68 ms`):** Local `opus-mt-tc-big-en-tr` INT8 quantized model (~227 MB) + 4096-entry LRU cache (`0.0045 ms` hits).

**Optional AI Upgrades:**
- **Context-Aware LLM Layer:** Keep offline CTranslate2 as the default, or optionally enable a 3-turn sliding dialogue window via local **Ollama**, **Gemini**, **DeepL**, or any **OpenAI-compatible** endpoint (with instant automatic fallback to local CT2).
- **Live Audio Mode:** Optional `faster-whisper` (INT8 CPU) for unsubtitled streams/videos.

**What's new in v1.5.0:**
- Native **macOS Apple Silicon (M1–M4) `.dmg`** with Cocoa click-through overlay alongside signed Windows x64 builds.
- Studio 2.0 dark UI, tight-hugging subtitle overlay, target-window lock (auto-hides on Alt+Tab), per-app profiles, JSON game glossaries, and SRT/Anki CSV export.

Currently ships with EN ➔ TR out of the box, with multi-language target pairs (`ES/DE/PT/JA`) next on the roadmap.

- **GitHub:** https://github.com/Andacbasaran/subvision-ai-subtitle-translator
- **Website:** https://subvisionai.andacbasaran.com

Happy to answer any questions about the OCR masking, CTranslate2 INT8 tuning, or cross-platform overlay architecture!
```

---

### 5️⃣ r/macapps (EN)
**Başlık:**
> SubVision AI v1.5 — Free & open-source offline real-time on-screen subtitle translator, now native on macOS Apple Silicon (M1–M4)

**İçerik:**
```markdown
Hey r/macapps!

I just shipped **SubVision AI v1.5.0**, now packaged as a native **macOS Apple Silicon (M1–M4) `.dmg`** with a native Cocoa click-through overlay.

**What it does:**
Press `F7` to select any subtitle region on your screen (movies, YouTube, Twitch, games, lectures), press `F8`, and SubVision AI translates English subtitles into Turkish in real time (**~88 ms**) directly over the original text — 100% offline on CPU.

**Highlights:**
- **100% Offline & Private:** Runs locally via RapidOCR ONNX + CTranslate2 INT8 (no account, no cloud API required).
- **Native Click-Through Overlay:** Tightly hugs the original subtitle box and hides automatically when you switch windows.
- **Optional Upgrades:** 3-turn context translation via local Ollama/Gemini/DeepL, optional `faster-whisper` live audio mode, per-app profiles, and SRT/Anki CSV export.
- **Free & Open Source (MIT):** Direct `.dmg` download + Homebrew Cask manifest in the repo.

Download: https://subvisionai.andacbasaran.com
GitHub: https://github.com/Andacbasaran/subvision-ai-subtitle-translator

*(Currently EN ➔ TR; multi-language pairs like ES/DE/PT/JA are on the roadmap — PRs welcome!)*
```

---

### 6️⃣ Hacker News — Show HN (EN)
**Başlık:**
> Show HN: SubVision AI – ~88ms offline, 0 MB VRAM on-screen subtitle translator

**İçerik (Text / First Comment):**
```text
Hi HN,

I built SubVision AI (MIT), a local real-time subtitle translator for games, movies, and streams that runs entirely on CPU (~88 ms end-to-end, 0 MB VRAM) on Windows x64 and macOS Apple Silicon.

Repo: https://github.com/Andacbasaran/subvision-ai-subtitle-translator
Site: https://subvisionai.andacbasaran.com

A few engineering choices that made it feel instant in practice:

1. Latest-Frame-Wins async pipeline: Capture/OCR and NMT run on decoupled threads with a single latest-slot instead of a FIFO queue. During fast dialogue, stale lines are dropped immediately rather than piling up lag.
2. Two-stage Frame Diff Lock (0.18 ms): Downsamples the ROI to 64x16 and skips OCR completely while a subtitle stays on screen (~0.2% CPU idle).
3. Direct line-projection CRNN (~20 ms): Instead of running full DBNet text detection on every frame, an adaptive local-contrast + colored speaker mask segments subtitle lines and batches them straight into RapidOCR's CRNN recognizer, with an anti-phantom plausibility filter to ignore HUD/sky noise.
4. CTranslate2 INT8 (~68 ms) + 4096-entry LRU cache: Runs opus-mt-tc-big-en-tr quantized to INT8 (~227 MB) with dynamic max_length and repetition_penalty=1.15. Optionally supports a 3-turn sliding context window via local Ollama, Gemini, DeepL, or OpenAI-compatible endpoints with automatic local fallback.
5. Native click-through overlays: Uses WDA_EXCLUDEFROMCAPTURE on Windows and native Cocoa overlay flags on macOS so the capture loop never reads its own translation, plus a target-window focus tracker that hides subtitles on Alt+Tab.

Currently targets EN->TR; next up is a pluggable model selector for other OPUS-MT / CTranslate2 language pairs. Would appreciate any feedback on the pipeline or architecture.
```

---

### 7️⃣ Product Hunt (EN)
- **Name:** `SubVision AI`
- **Tagline (≤ 60 chars):** `~88ms offline, 0 MB VRAM subtitle translator for games & video`
- **Short Description:**
  > Translate on-screen subtitles in real time (~88 ms) on Windows & macOS Apple Silicon — 100% offline on CPU with zero FPS drop. Optional Ollama/Gemini context layer & Whisper live audio. Free & MIT open source.
- **Topics:** `Open Source`, `Artificial Intelligence`, `Mac`, `Windows`, `Gaming`
- **Maker's First Comment:**
  ```markdown
  Hey Product Hunt! 👋

  I built **SubVision AI** because I wanted a way to translate English subtitles in PC games, movies, and live streams without losing GPU VRAM, paying monthly API fees, or dealing with clunky laggy boxes.

  **What makes v1.5 special:**
  - ⚡ **~88 ms end-to-end on CPU (0 MB VRAM):** RapidOCR + CTranslate2 INT8 in an async Latest-Frame-Wins pipeline.
  - 🎯 **Tight-hugging overlay & Alt+Tab lock:** Automatically measures and covers the original subtitle cleanly, and hides when you switch windows.
  - 🍎 **Windows x64 & macOS Apple Silicon (M1–M4):** Native builds + cross-platform GitHub auto-updater.
  - 🧠 **Optional Power Modes:** Plug in local Ollama, Gemini, or DeepL for 3-turn dialogue context, turn on `faster-whisper` for unsubtitled streams, and export history to SRT or Anki CSV.
  - 💜 **100% Free & Open Source (MIT).**

  Right now it ships with EN ➔ TR out of the box, and we're opening the roadmap for EN ➔ ES/DE/PT/JA next. Would love to hear what games or language pairs you'd like to see supported!
  ```

---

## 4. Önerilen Lansman Haftası Takvimi

| Gün | Aksiyon | Hedef |
| :---: | :--- | :--- |
| **Gün 1** | `assets/demo.gif` + `demo_social.mp4` kaydet, GitHub About / Topics / Social Preview & Discussions'ı aç. | Vitrin dönüşüm oranını maksimize et. |
| **Gün 2** | **Technopat Sosyal**, **DonanımHaber**, **r/veYakinEvren**, **r/GeymingTR** paylaşımları. | İlk gerçek kullanıcı dalgası, oyun uyumluluk geri bildirimi ve erken yıldız ivmesi. |
| **Gün 3** | **X (Twitter)** TR + EN lansman thread'i (`demo_social.mp4` videolu). | Görsel paylaşım & geliştirici çevresi keşfi. |
| **Gün 4** | **r/LocalLLaMA**, **r/opensource**, **r/macapps** paylaşımları. | Küresel açık kaynak & macOS topluluğu. |
| **Gün 5** | **Hacker News (Show HN)** (TR saatiyle 16:00–17:30 arası önerilir). | Mühendislik odaklı küresel trafik ve GitHub yıldız patlaması. |
| **Gün 6–7** | **Product Hunt** lansmanı + gelen Issue/PR/Dil taleplerine hızlı yanıt. | Uzun kuyruklu keşif ve ilk harici katkıcılar. |
