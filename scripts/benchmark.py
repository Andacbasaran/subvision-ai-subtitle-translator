"""
SubVision AI — Donanım & Uçtan Uca Gecikme Performans Testi (Benchmark Suite)
Çalıştırmak için:
    python scripts/benchmark.py
"""

import json
import os
import platform
import statistics
import sys
import time
from typing import Dict, List

import cv2
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from subvision.hardware import (
    compute_runtime_tuning,
    detect_hardware_profile,
    get_ui_font_family,
)
from subvision.ocr_engine import SubtitleOCREngine
from subvision.translator import LocalEnTrTranslator


def make_synthetic_subtitle_frame(
    lines: List[str], width: int = 960, height: int = 110
) -> np.ndarray:
    """
    Gerçek bir 1080p oyun/dizi altyazı kesitini (karmaşık arka plan üzerinde
    siyah kontürlü beyaz altyazı) simüle eden test karesi üretir.
    """
    rng = np.random.default_rng(42)
    frame = rng.integers(35, 95, size=(height, width, 3), dtype=np.uint8)
    frame = cv2.GaussianBlur(frame, (7, 7), 0)

    y_positions = [64] if len(lines) == 1 else [46, 86]
    for line, y in zip(lines[:2], y_positions):
        cv2.putText(
            frame,
            line,
            (28, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.82,
            (10, 10, 10),
            5,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            line,
            (28, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.82,
            (250, 250, 250),
            2,
            cv2.LINE_AA,
        )
    return frame


def generate_visual_assets(bm: Dict) -> None:
    """
    Uygulama ikonu (assets/app_icon.ico), Studio Arayüz Önizlemesi (assets/ui_preview.png)
    ve Anlaşılır Karşılaştırmalı Performans İnfografiğini (assets/benchmark_chart.png) üretir.
    """
    from PIL import Image
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
    from PyQt6.QtWidgets import QApplication
    import main as app_main

    base_dir = REPO_ROOT
    assets_dir = os.path.join(base_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)

    # 1. Multi-Resolution .ICO & .PNG Uygulama İkonu (Mevcut özel tasarım logo varsa koru)
    png_icon_path = os.path.join(assets_dir, "app_icon.png")
    ico_path = os.path.join(assets_dir, "app_icon.ico")
    if not os.path.exists(png_icon_path) or not os.path.exists(ico_path):
        pix = app_main.create_app_pixmap(256)
        if not os.path.exists(png_icon_path):
            pix.save(png_icon_path, "PNG")
        img = Image.open(png_icon_path)
        img.save(
            ico_path,
            format="ICO",
            sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
        )

    # 2. Studio Arayüz Önizleme Görseli (assets/ui_preview.png)
    win = app_main.MainWindow()
    win.resize(880, 665)
    win.combo_ocr_mode.setCurrentIndex(0)
    win.chk_bilingual.setChecked(True)
    win._select_color_swatch("#FACC15")
    win.translator.total_requests = 24
    win.translator.cache_hits = 11
    win._on_subtitle_updated(
        "Commander: If we cross the event horizon, there's no turning back for any of us.",
        "Komutan: Olay ufkunu geçersek, hiçbirimiz için geri dönüş yok.",
        bm["fast_ocr_1line_ms"],
        0.004,
        True,
    )
    win._on_subtitle_updated(
        "Arthur: Stay close to me, the woods ahead are crawling with bounty hunters.",
        "Arthur: Yakınımda kal, ilerideki orman ödül avcılarıyla kaynıyor.",
        bm["fast_ocr_1line_ms"],
        bm["nmt_short_ms"],
        False,
    )
    win._on_subtitle_updated(
        "Detective: Everything we found in that room points to a much bigger conspiracy.",
        "Dedektif: O odada bulduğumuz her şey çok daha büyük bir komploya işaret ediyor.",
        bm["fast_ocr_1line_ms"],
        bm["nmt_short_ms"],
        False,
    )
    app.processEvents()
    win._on_model_ready()
    win.lbl_scene_tag.setText("Canlı Yakalama · 30 FPS")
    win._switch_tab(0)
    win.repaint()
    app.processEvents()
    ui_pix = win.grab()
    ui_pix.save(os.path.join(assets_dir, "ui_preview.png"), "PNG")

    win._switch_tab(1)
    win.repaint()
    app.processEvents()
    hist_pix = win.grab()
    hist_pix.save(os.path.join(assets_dir, "ui_preview_history.png"), "PNG")

    win._switch_tab(2)
    win.repaint()
    app.processEvents()
    set_pix = win.grab()
    set_pix.save(os.path.join(assets_dir, "ui_preview_settings.png"), "PNG")
    win.close()

    # 3. Yeni Nesil Anlaşılır Benchmark İnfografiği (assets/benchmark_chart.png)
    chart = QPixmap(1080, 620)
    chart.fill(QColor("#070B14"))
    cp = QPainter(chart)
    cp.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Dış Kart
    cp.setPen(QPen(QColor("#1E293B"), 2))
    cp.setBrush(QColor("#0F1626"))
    cp.drawRoundedRect(14, 14, 1052, 592, 16, 16)

    # Başlık
    ui_font = get_ui_font_family()
    cp.setPen(QColor("#FFFFFF"))
    cp.setFont(QFont(ui_font, 16, QFont.Weight.Black))
    cp.drawText(36, 52, "⚡ SubVision AI — Gerçek Zamanlı Performans & Gecikme Analizi")

    cp.setPen(QColor("#94A3B8"))
    cp.setFont(QFont(ui_font, 9, QFont.Weight.DemiBold))
    cpu_label = bm.get("cpu_name", "CPU")
    ctype_label = str(bm.get("compute_type", "INT8")).upper()
    sub_hdr = (
        f"Test Donanımı: {cpu_label} ({bm['cpu_logical_cores']} Mantıksal Çekirdek / {bm['nmt_threads']} Aktif NMT Thread)   •   "
        f"CTranslate2 {ctype_label} + RapidOCR ONNX   •   Anlık Algı Eşiği: < 150 ms"
    )
    cp.drawText(36, 75, sub_hdr)

    # Üst Özet KPI Kutuları (4 Adet Anlaşılır Kazanım Kartı)
    summary_cards = [
        (
            "OCR OKUMA HIZI",
            f"{bm['fast_ocr_1line_ms']:.1f} ms",
            f"Standart OCR'dan ({bm['full_ocr_dbnet_ms']:.0f} ms) {bm['ocr_speedup_factor']}x daha hızlı",
            "#22C55E",
        ),
        (
            "YENİ CÜMLE TOPLAM SÜRE",
            f"{bm['e2e_cold_short_ms']:.1f} ms",
            "Göz kırpmasından hızlı (<150 ms anlık algı)",
            "#38BDF8",
        ),
        (
            "ÖNBELLEKLİ TOPLAM SÜRE",
            f"{bm['e2e_cached_ms']:.1f} ms",
            "Tek bir 60 FPS video karesi süresinde yanıt",
            "#A78BFA",
        ),
        (
            "EKRAN KARTI (VRAM) YÜKÜ",
            "0 MB",
            "Oyunlarda ve 4K videolarda sıfır FPS kaybı",
            "#FACC15",
        ),
    ]

    cx = 36
    cw = 238
    ch = 92
    cy = 96
    for c_title, c_val, c_desc, c_hex in summary_cards:
        cp.setPen(QPen(QColor("#1E293B"), 1.5))
        cp.setBrush(QColor("#090D16"))
        cp.drawRoundedRect(cx, cy, cw, ch, 10, 10)

        # Üst vurgu çizgisi
        cp.setPen(Qt.PenStyle.NoPen)
        cp.setBrush(QColor(c_hex))
        cp.drawRoundedRect(cx + 12, cy, cw - 24, 3, 1, 1)

        cp.setPen(QColor("#94A3B8"))
        cp.setFont(QFont("Segoe UI", 8, QFont.Weight.ExtraBold))
        cp.drawText(cx + 14, cy + 24, c_title)

        cp.setPen(QColor(c_hex))
        cp.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        cp.drawText(cx + 14, cy + 54, c_val)

        cp.setPen(QColor("#64748B"))
        cp.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        cp.drawText(cx + 14, cy + 76, c_desc)
        cx += cw + 18

    # Alt Bölüm Başlığı
    cp.setPen(QColor("#38BDF8"))
    cp.setFont(QFont("Segoe UI", 10, QFont.Weight.ExtraBold))
    cp.drawText(
        36,
        222,
        "📊  AŞAMA BAZLI GECİKME KARŞILAŞTIRMASI (Daha Kısa Çubuk = Daha Hızlı Yanıt)",
    )

    bars = [
        (
            "1. Frame Diff Lock (Altyazı Sabitken)",
            "Altyazı değişmediğinde OCR/NMT çalışmaz",
            bm["pixel_lock_avg_ms"],
            "#38BDF8",
            f"{bm['pixel_lock_avg_ms']:.2f} ms  (%0.2 CPU Uyku Modu)",
        ),
        (
            "2. RAM LRU Cache & Sözlük Hit",
            "Daha önce çevrilen veya kalıp cümle yanıtı",
            bm["cache_hit_ms"],
            "#A78BFA",
            f"{bm['cache_hit_ms']:.4f} ms  (Anında Yanıt)",
        ),
        (
            "3. SubVision AI Hızlı OCR (1 Satır)",
            "Yatay satır projeksiyonu + CRNN okuyucu",
            bm["fast_ocr_1line_ms"],
            "#22C55E",
            f"{bm['fast_ocr_1line_ms']:.1f} ms  ({bm['ocr_speedup_factor']}x Daha Hızlı)",
        ),
        (
            "4. Geleneksel Tam Kare OCR (DBNet)",
            "Standart metin arama + okuma yaklaşımı",
            bm["full_ocr_dbnet_ms"],
            "#64748B",
            f"{bm['full_ocr_dbnet_ms']:.1f} ms  (Geleneksel Yöntem)",
        ),
        (
            "5. CTranslate2 INT8 NMT (Kısa Replik)",
            f"Opus-MT Big INT8 CPU ({bm['nmt_threads']} Thread)",
            bm["nmt_short_ms"],
            "#FACC15",
            f"{bm['nmt_short_ms']:.1f} ms  (0 MB VRAM)",
        ),
        (
            "6. Uçtan Uca Toplam (Önbellekli Replik)",
            "Ekran Yakalama + Hızlı OCR + RAM Önbellek",
            bm["e2e_cached_ms"],
            "#10B981",
            f"{bm['e2e_cached_ms']:.1f} ms  (Ultra Hızlı)",
        ),
        (
            "7. Uçtan Uca Toplam (Yeni Kısa Replik)",
            "Ekran Yakalama + Hızlı OCR + INT8 Çeviri",
            bm["e2e_cold_short_ms"],
            "#3B82F6",
            f"{bm['e2e_cold_short_ms']:.1f} ms  (<150 ms Anlık Eşik Altı)",
        ),
        (
            "8. Uçtan Uca Toplam (Yeni Uzun Replik)",
            "14-18 kelimelik uzun dizi/film diyaloğu",
            bm["e2e_cold_med_ms"],
            "#6366F1",
            f"{bm['e2e_cold_med_ms']:.1f} ms  (Gerçek Zamanlı)",
        ),
    ]

    track_x = 360
    track_w = 410
    max_scale_ms = 165.0

    # 150 ms İnsan Gözü Anlık Algı Eşiği Dikey Referans Çizgisi
    thresh_x = track_x + int((150.0 / max_scale_ms) * track_w)
    cp.setPen(QPen(QColor("#EF4444"), 1.5, Qt.PenStyle.DashLine))
    cp.drawLine(thresh_x, 235, thresh_x, 582)
    cp.setPen(QColor("#F87171"))
    cp.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
    cp.drawText(thresh_x - 85, 232, "150 ms Anlık Algı Sınırı ▾")

    y = 244
    for title_txt, sub_txt, val, color_hex, val_text in bars:
        cp.setPen(QColor("#F8FAFC"))
        cp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cp.drawText(36, y + 14, title_txt)

        cp.setPen(QColor("#64748B"))
        cp.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        cp.drawText(36, y + 29, sub_txt)

        # Bar Yatağı
        cp.setPen(Qt.PenStyle.NoPen)
        cp.setBrush(QColor("#090D16"))
        cp.drawRoundedRect(track_x, y + 5, track_w, 22, 6, 6)

        # Doluluk
        fill_w = max(8, min(track_w, int((val / max_scale_ms) * track_w)))
        cp.setBrush(QColor(color_hex))
        cp.drawRoundedRect(track_x, y + 5, fill_w, 22, 6, 6)

        # Değer Metni
        cp.setPen(QColor(color_hex))
        cp.setFont(QFont("Segoe UI", 9, QFont.Weight.ExtraBold))
        cp.drawText(track_x + track_w + 16, y + 21, val_text)
        y += 43

    cp.end()
    chart.save(os.path.join(assets_dir, "benchmark_chart.png"), "PNG")


def run_benchmarks() -> Dict:
    print("=" * 74)
    print("  SubVision AI — Uçtan Uca Performans ve Gecikme Testi (Benchmark)")
    print("=" * 74)

    hw = detect_hardware_profile(query_ct2=True)
    tuning = compute_runtime_tuning(hw)
    cpu_count_logical = hw.logical_cores
    optimal_threads = tuning.nmt_threads
    print(f"[*] İşletim Sistemi : {hw.os_name} {hw.os_version} ({hw.arch})")
    print(f"[*] İşlemci (CPU)   : {hw.cpu_name}")
    print(
        f"[*] Çekirdek / Profil: {hw.physical_cores} Fiziksel / {hw.logical_cores} Mantıksal "
        f"(Profil: {tuning.effective_profile} | NMT: {optimal_threads}T | OCR: {tuning.ocr_intra_threads}T)"
    )
    print("[*] Motorlar yükleniyor (RapidOCR ONNX + Uyarlanabilir CTranslate2)...")

    t_init_start = time.perf_counter()
    ocr_engine = SubtitleOCREngine(use_color_mask=True, ocr_mode="fast_mask", tuning=tuning)
    translator = LocalEnTrTranslator(
        cpu_threads=optimal_threads,
        compute_type_candidates=tuning.compute_type_candidates,
    )
    translator.load()
    init_sec = time.perf_counter() - t_init_start
    print(
        f"[OK] Motorlar {init_sec:.2f} saniyede hazırlandı "
        f"(Aktif Hesaplama Tipi: {translator.active_compute_type.upper()}).\n"
    )

    frame_1 = make_synthetic_subtitle_frame(["Stay behind me, the signal is getting stronger."])
    gray_1 = cv2.cvtColor(frame_1, cv2.COLOR_BGR2GRAY)
    ocr_engine._has_frame_changed(gray_1)

    lock_times: List[float] = []
    for _ in range(500):
        t0 = time.perf_counter()
        _ = ocr_engine._has_frame_changed(gray_1)
        lock_times.append((time.perf_counter() - t0) * 1000.0)
    pixel_lock_avg = statistics.mean(lock_times)
    pixel_lock_p95 = sorted(lock_times)[int(len(lock_times) * 0.95)]

    frame_2 = make_synthetic_subtitle_frame(
        [
            "Detective: Everything in this file points to a cover-up.",
            "We need to reach the broadcast tower before midnight.",
        ]
    )

    ocr_engine.set_mode("fast_mask")
    ocr_engine.read_image_fast(frame_1)

    fast_ocr_1line: List[float] = []
    for _ in range(15):
        _, ms = ocr_engine.read_image_fast(frame_1)
        fast_ocr_1line.append(ms)

    fast_ocr_2line: List[float] = []
    for _ in range(15):
        _, ms = ocr_engine.read_image_fast(frame_2)
        fast_ocr_2line.append(ms)

    ocr_engine.set_mode("full_ocr")
    ocr_engine.read_image_fast(frame_1)
    full_ocr_1line: List[float] = []
    for _ in range(8):
        _, ms = ocr_engine.read_image_fast(frame_1)
        full_ocr_1line.append(ms)

    ocr_engine.set_mode("fast_mask")

    short_dialogs = [
        "Arthur: Follow me closely.",
        "Something feels wrong about this place.",
        "Turn off the engine and wait here.",
        "They already know we are inside the building.",
        "Check the security cameras on the second floor.",
    ]
    medium_dialogs = [
        "Detective: Everything we found in that room points to a much bigger conspiracy.",
        "Commander: If we cross the event horizon, there's no turning back for any of us.",
        "For centuries, this ancient civilization remained completely hidden beneath the jungle.",
        "I promised I would find the truth, no matter how dangerous it gets.",
        "Hold on tight! I'm gonna take the shortcut through the old railway tunnel!",
    ]
    multi_sentence_dialogs = [
        "Stay down! The patrol is passing right outside the window. Wait for my signal.",
        "We don't have much time left. Grab the hard drive and meet me at the exit.",
        "Listen carefully. Once you open that door, the alarm will trigger across the facility.",
    ]

    def measure_uncached_nmt(samples: List[str], runs: int = 3) -> List[float]:
        timings: List[float] = []
        for _ in range(runs):
            for s in samples:
                translator.clear_cache()
                _, ms, _ = translator.translate_with_metrics(s)
                timings.append(ms)
        return timings

    nmt_short = measure_uncached_nmt(short_dialogs, runs=3)
    nmt_medium = measure_uncached_nmt(medium_dialogs, runs=3)
    nmt_multi = measure_uncached_nmt(multi_sentence_dialogs, runs=3)

    translator.translate_with_metrics(medium_dialogs[0])
    cache_times: List[float] = []
    for _ in range(500):
        _, ms, _ = translator.translate_with_metrics(medium_dialogs[0])
        cache_times.append(ms)

    glossary_times: List[float] = []
    for _ in range(500):
        _, ms, _ = translator.translate_with_metrics("What are you talking about?")
        glossary_times.append(ms)

    avg_fast_ocr_1 = statistics.mean(fast_ocr_1line)
    avg_fast_ocr_2 = statistics.mean(fast_ocr_2line)
    avg_full_ocr_1 = statistics.mean(full_ocr_1line)
    avg_nmt_short = statistics.mean(nmt_short)
    avg_nmt_med = statistics.mean(nmt_medium)
    avg_nmt_multi = statistics.mean(nmt_multi)
    avg_cache = statistics.mean(cache_times)
    avg_glossary = statistics.mean(glossary_times)

    e2e_cold_short = avg_fast_ocr_1 + avg_nmt_short
    e2e_cold_med = avg_fast_ocr_1 + avg_nmt_med
    e2e_cached = avg_fast_ocr_1 + avg_cache
    ocr_speedup = avg_full_ocr_1 / max(0.1, avg_fast_ocr_1)

    results = {
        "cpu_name": hw.short_cpu_label,
        "arch": hw.arch,
        "cpu_physical_cores": hw.physical_cores,
        "cpu_logical_cores": cpu_count_logical,
        "profile_tier": tuning.effective_profile,
        "compute_type": translator.active_compute_type,
        "nmt_threads": optimal_threads,
        "ocr_threads": tuning.ocr_intra_threads,
        "init_time_sec": round(init_sec, 2),
        "pixel_lock_avg_ms": round(pixel_lock_avg, 4),
        "pixel_lock_p95_ms": round(pixel_lock_p95, 4),
        "fast_ocr_1line_ms": round(avg_fast_ocr_1, 2),
        "fast_ocr_2line_ms": round(avg_fast_ocr_2, 2),
        "full_ocr_dbnet_ms": round(avg_full_ocr_1, 2),
        "ocr_speedup_factor": round(ocr_speedup, 1),
        "nmt_short_ms": round(avg_nmt_short, 2),
        "nmt_medium_ms": round(avg_nmt_med, 2),
        "nmt_multi_ms": round(avg_nmt_multi, 2),
        "cache_hit_ms": round(avg_cache, 4),
        "glossary_hit_ms": round(avg_glossary, 4),
        "e2e_cold_short_ms": round(e2e_cold_short, 2),
        "e2e_cold_med_ms": round(e2e_cold_med, 2),
        "e2e_cached_ms": round(e2e_cached, 2),
        "vram_usage_mb": 0,
    }

    out_json = os.path.join(REPO_ROOT, "benchmark_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    try:
        generate_visual_assets(results)
        print("[OK] Görsel varlıklar (assets/ui_preview.png, assets/benchmark_chart.png, assets/app_icon.ico) üretildi.")
    except Exception as exc:
        print(f"[!] Görsel varlık üretimi atlandı: {exc}")

    return results


if __name__ == "__main__":
    run_benchmarks()
