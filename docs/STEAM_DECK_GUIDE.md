# SubVision AI — Steam Deck (SteamOS) & Linux Rehberi / Guide

> 🇹🇷 Türkçe bölüm aşağıda | 🇬🇧 English section follows below

---

## 🇹🇷 Türkçe Rehber

### 1. Masaüstü Modu (Desktop Mode) Kurulumu
Steam Deck üzerinde SubVision AI kurulumunu **Masaüstü Modu (Desktop Mode)** içinde yapın:
1. **STEAM** düğmesine basın → **Güç (Power)** → **Masaüstüne Geç (Switch to Desktop)**.
2. Tarayıcınızdan [GitHub Releases](https://github.com/andacbasaran/subvision-ai-subtitle-translator/releases) sayfasına gidin ve Linux paketini indirin:
   - **Taşınabilir Arşiv (Önerilen):** `SubVisionAI-v<sürüm>-Linux-x86_64.tar.gz`
   - **AppImage (mevcutsa):** `SubVisionAI-v<sürüm>-Linux-x86_64.AppImage`

### 2. Çalıştırma (`.tar.gz` veya `.AppImage`)

#### Seçenek A: `.tar.gz` Taşınabilir Paket
```bash
mkdir -p ~/Applications
tar -xzf ~/Downloads/SubVisionAI-v*-Linux-x86_64.tar.gz -C ~/Applications
~/Applications/SubVisionAI/SubVisionAI
```

#### Seçenek B: `.AppImage`
```bash
chmod +x ~/Downloads/SubVisionAI-v*-Linux-x86_64.AppImage
~/Downloads/SubVisionAI-v*-Linux-x86_64.AppImage
```

> **Not:** İlk açılışta çevrimdışı çeviri modeli (~300 MB) otomatik indirilir ve kullanıcı dizininde saklanır (`~/.local/share/SubVisionAI` / `~/.config/SubVisionAI`).

### 3. Steam Dışı Oyun Olarak Ekleme ve Oyun İçi İpuçları
1. Masaüstü Modunda Steam'i açın → **Oyunlar (Games)** → **Steam Dışı Oyun Ekle (Add a Non-Steam Game to My Library)**.
2. `~/Applications/SubVisionAI/SubVisionAI` (veya `.AppImage`) dosyasını seçip ekleyin.
3. **Çerçevesiz Pencere (Borderless Windowed):** Altyazı katmanının (overlay) oyunun üzerinde görünebilmesi için oyun ayarlarını **Borderless Windowed** veya **Windowed** moduna alın. Tam ekran (Exclusive Fullscreen) modda katman oyunun arkasında kalabilir.
4. **Steam Deck Oyun Modu (Gaming Mode / Gamescope):** Gamescope her oyunu ayrı bir Wayland penceresinde izole ettiği için, SubVision AI'nin en kararlı kullanımı **Masaüstü Modu (KDE Plasma / X11)** içindedir.

### 4. X11 / XWayland, Ekran Yakalama (`mss`) ve Kısayollar
- SubVision AI ekran görüntüsü yakalamak için `mss` (X11) kullanır.
- **SteamOS Masaüstü Modu** varsayılan olarak X11 / XWayland desteklidir; ekstra ayar gerekmez.
- **Saf Wayland kullanan Linux dağıtımlarında (Fedora, Ubuntu 24.04+, Arch Wayland):** Ekran yakalama boş/siyah görünüyorsa veya global kısayollar çalışmıyorsa uygulamayı XWayland üzerinden başlatın:
  ```bash
  QT_QPA_PLATFORM=xcb ~/Applications/SubVisionAI/SubVisionAI
  ```
- Çeviri alanını (ROI) ekranın alt kısmındaki altyazı bölgesine daraltmak hem OCR hızını artırır hem de Steam Deck pil ömrünü korur.

---

## 🇬🇧 English Guide

### 1. Desktop Mode Setup (Steam Deck / SteamOS)
Install SubVision AI from **Desktop Mode** on Steam Deck:
1. Press the **STEAM** button → **Power** → **Switch to Desktop**.
2. Open a browser and download the Linux package from [GitHub Releases](https://github.com/andacbasaran/subvision-ai-subtitle-translator/releases):
   - **Portable Archive (Recommended):** `SubVisionAI-v<version>-Linux-x86_64.tar.gz`
   - **AppImage (when available):** `SubVisionAI-v<version>-Linux-x86_64.AppImage`

### 2. Launching (`.tar.gz` or `.AppImage`)

#### Option A: `.tar.gz` Portable Archive
```bash
mkdir -p ~/Applications
tar -xzf ~/Downloads/SubVisionAI-v*-Linux-x86_64.tar.gz -C ~/Applications
~/Applications/SubVisionAI/SubVisionAI
```

#### Option B: `.AppImage`
```bash
chmod +x ~/Downloads/SubVisionAI-v*-Linux-x86_64.AppImage
~/Downloads/SubVisionAI-v*-Linux-x86_64.AppImage
```

> **Note:** On first launch, the offline translation model (~300 MB) is downloaded automatically and cached under your user profile (`~/.local/share/SubVisionAI` / `~/.config/SubVisionAI`).

### 3. Adding as a Non-Steam Game & Borderless Windowed Tips
1. Open Steam in Desktop Mode → **Games** → **Add a Non-Steam Game to My Library**.
2. Browse to `~/Applications/SubVisionAI/SubVisionAI` (or the `.AppImage`) and add it.
3. **Borderless Windowed Mode:** Set your game's display mode to **Borderless Windowed** or **Windowed** so the transparent subtitle overlay renders on top of the game. Exclusive Fullscreen may hide overlay windows.
4. **Gaming Mode (Gamescope) Note:** Because Gamescope isolates each game into its own Wayland surface, running games and SubVision AI together is most reliable in **Desktop Mode (KDE Plasma / X11)**.

### 4. X11 / XWayland Note (`mss` Screen Capture & Global Hotkeys)
- SubVision AI uses `mss` (X11) for fast, low-overhead screen capture and global hotkeys.
- **SteamOS Desktop Mode** provides X11 / XWayland out of the box.
- **Wayland Linux desktops (Ubuntu 24.04+, Fedora, Arch Wayland):** If screen capture returns blank frames or global hotkeys do not register, launch via XWayland (`xcb`) or switch to an X11 session:
  ```bash
  QT_QPA_PLATFORM=xcb ~/Applications/SubVisionAI/SubVisionAI
  ```
- Keeping the OCR capture region (ROI) tightly fitted around the subtitle area improves frame latency and saves battery on Steam Deck.
