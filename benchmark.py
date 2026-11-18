"""
SubVision AI — Donanım & Uçtan Uca Gecikme Performans Testi (Benchmark Suite)
Çalıştırmak için:
    python benchmark.py
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

from ocr_engine import SubtitleOCREngine
from translator import LocalEnTrTranslator


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
        # Dış siyah kontür (Outline)
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
        # İç parlak beyaz harfler
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
    Uygulama ikonu (assets/app_icon.ico), Arayüz Önizlemesi (assets/ui_preview.png)
    ve Performans Grafiğini (assets/benchmark_chart.png) otomatik oluşturur.
    """
    from PIL import Image
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
    from PyQt6.QtWidgets import QApplication
    import main as app_main

    base_dir = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(base_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)

    # 1. Multi-Resolution .ICO & .PNG Uygulama İkonu
    pix = QPixmap(256, 256)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 256, 256)
    grad.setColorAt(0.0, QColor("#4F46E5"))
    grad.setColorAt(0.5, QColor("#2563EB"))
    grad.setColorAt(1.0, QColor("#06B6D4"))
    p.setBrush(grad)
    p.setPen(QPen(QColor("#38BDF8"), 8))
    p.drawRoundedRect(16, 16, 224, 224, 52, 52)

    p.setPen(QColor("#FFFFFF"))
    p.setFont(QFont("Segoe UI", 68, QFont.Weight.Black))
    p.drawText(QRect(16, 28, 224, 115), Qt.AlignmentFlag.AlignCenter, "TR")

    p.setPen(QPen(QColor("#FACC15"), 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(52, 172, 204, 172)
    p.setPen(QPen(QColor("#E2E8F0"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(76, 204, 180, 204)
    p.end()

    png_icon_path = os.path.join(assets_dir, "app_icon.png")
    ico_path = os.path.join(assets_dir, "app_icon.ico")
    pix.save(png_icon_path, "PNG")
    img = Image.open(png_icon_path)
    img.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )

    # 2. Arayüz Önizleme Görseli (assets/ui_preview.png)
    win = app_main.MainWindow()
    win.resize(960, 840)
    win._on_model_ready()
    win.translator.total_requests = 14
    win.translator.cache_hits = 6
    win._on_subtitle_updated(
        "Commander: If we cross the event horizon, there's no turning back for any of us.",
        "Komutan: Olay ufkunu geçersek, hiçbirimiz için geri dönüş yok.",
        bm["fast_ocr_1line_ms"],
        0.01,
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
    win.lbl_scene_tag.setText("Mod: Canlı Ekran Yakalama (30 FPS / 1080p)")
    win.repaint()
    app.processEvents()
    ui_pix = win.grab()
    ui_pix.save(os.path.join(assets_dir, "ui_preview.png"), "PNG")
    win.close()

    # 3. Performans Benchmark Grafiği (assets/benchmark_chart.png)
    chart = QPixmap(1020, 520)
    chart.fill(QColor("#0B0F19"))
    cp = QPainter(chart)
    cp.setRenderHint(QPainter.RenderHint.Antialiasing)

    cp.setPen(QPen(QColor("#1E293B"), 2))
    cp.setBrush(QColor("#111827"))
    cp.drawRoundedRect(16, 16, 988, 488, 14, 14)

    cp.setPen(QColor("#F8FAFC"))
    cp.setFont(QFont("Segoe UI", 15, QFont.Weight.Black))
    cp.drawText(40, 54, "⚡ SubVision AI — Gerçek Zamanlı Performans & Gecikme Analizi (ms)")
    cp.setPen(QColor("#94A3B8"))
    cp.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
    sub_hdr = (
        f"Test Ortamı: {bm['cpu_logical_cores']} Mantıksal Çekirdek CPU ({bm['nmt_threads']} NMT Thread)  |  "
        f"CTranslate2 INT8 + RapidOCR ONNX  |  GPU/VRAM: 0 MB"
    )
    cp.drawText(40, 78, sub_hdr)

    bars = [
        (
            "Piksel Değişim Kilidi (Sabit Kare)",
            bm["pixel_lock_avg_ms"],
            "#38BDF8",
            f"{bm['pixel_lock_avg_ms']:.2f} ms  (%0 CPU Uyku Modu)",
        ),
        (
            "LRU RAM Önbellek & Sözlük Hit",
            bm["cache_hit_ms"],
            "#A78BFA",
            f"{bm['cache_hit_ms']:.4f} ms  (Anında Yanıt)",
        ),
        (
            "Hızlı Satır Projeksiyonlu OCR (1 Satır)",
            bm["fast_ocr_1line_ms"],
            "#22C55E",
            f"{bm['fast_ocr_1line_ms']:.1f} ms  ({bm['ocr_speedup_factor']}x Daha Hızlı)",
        ),
        (
            "Standart Tam Kare OCR (DBNet + CRNN)",
            bm["full_ocr_dbnet_ms"],
            "#64748B",
            f"{bm['full_ocr_dbnet_ms']:.1f} ms  (Geleneksel OCR)",
        ),
        (
            "CTranslate2 INT8 NMT (Kısa Diyalog)",
            bm["nmt_short_ms"],
            "#FACC15",
            f"{bm['nmt_short_ms']:.1f} ms  (Opus-MT Big INT8)",
        ),
        (
            "Uçtan Uca Gecikme (Önbellekli Altyazı)",
            bm["e2e_cached_ms"],
            "#10B981",
            f"{bm['e2e_cached_ms']:.1f} ms  (OCR + Önbellek Hit)",
        ),
        (
            "Uçtan Uca Gecikme (Yeni Kısa Altyazı)",
            bm["e2e_cold_short_ms"],
            "#3B82F6",
            f"{bm['e2e_cold_short_ms']:.1f} ms  (OCR + INT8 NMT)",
        ),
        (
            "Uçtan Uca Gecikme (Yeni Uzun Altyazı)",
            bm["e2e_cold_med_ms"],
            "#6366F1",
            f"{bm['e2e_cold_med_ms']:.1f} ms  (OCR + INT8 NMT)",
        ),
    ]

    y = 110
    for label, val, color_hex, val_text in bars:
        cp.setPen(QColor("#E2E8F0"))
        cp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cp.drawText(40, y + 17, label)

        track_x, track_w, track_h = 345, 360, 22
        cp.setPen(Qt.PenStyle.NoPen)
        cp.setBrush(QColor("#0B0F19"))
        cp.drawRoundedRect(track_x, y + 1, track_w, track_h, 6, 6)

        fill_w = max(8, min(track_w, int((val / 150.0) * track_w)))
        cp.setBrush(QColor(color_hex))
        cp.drawRoundedRect(track_x, y + 1, fill_w, track_h, 6, 6)

        cp.setPen(QColor(color_hex))
        cp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cp.drawText(track_x + track_w + 16, y + 17, val_text)
        y += 47

    cp.end()
    chart.save(os.path.join(assets_dir, "benchmark_chart.png"), "PNG")


def run_benchmarks() -> Dict:
    print("=" * 74)
    print("  SubVision AI — Uçtan Uca Performans ve Gecikme Testi (Benchmark)")
    print("=" * 74)

    cpu_count_logical = os.cpu_count() or 4
    optimal_threads = max(2, min(6, cpu_count_logical // 2))
    print(f"[*] İşletim Sistemi : {platform.system()} {platform.release()} ({platform.version()})")
    print(f"[*] İşlemci (CPU)   : {platform.processor()}")
    print(f"[*] Mantıksal Çekirdek: {cpu_count_logical} (NMT Aktif Thread: {optimal_threads})")
    print("[*] Motorlar yükleniyor (RapidOCR ONNX + CTranslate2 INT8)...")

    t_init_start = time.perf_counter()
    ocr_engine = SubtitleOCREngine(use_color_mask=True, ocr_mode="fast_mask")
    translator = LocalEnTrTranslator(cpu_threads=optimal_threads)
    translator.load()
    init_sec = time.perf_counter() - t_init_start
    print(f"[OK] Motorlar {init_sec:.2f} saniyede hazırlandı.\n")

    # 1. Piksel Değişim Kilidi (Boşta / Sabit Altyazı Kare Atlama Süresi)
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

    # 2. OCR Karşılaştırması: Fast Line Projection vs Standart DBNet Tam Kare OCR
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

    # 3. CTranslate2 INT8 NMT Çeviri Hızı (Kısa, Orta ve Çok Cümleli Diyaloglar)
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

    # 4. LRU Önbellek (Cache Hit) & Hazır Sözlük (Glossary) Süresi
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
        "cpu_logical_cores": cpu_count_logical,
        "nmt_threads": optimal_threads,
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

    print("📊 ÖZET PERFORMANS TABLOSU")
    print("-" * 74)
    print(f"1. Piksel Değişim Kilidi (Sabit Kare Atlama)      : {pixel_lock_avg:.4f} ms (P95: {pixel_lock_p95:.4f} ms)")
    print(f"2. Hızlı Satır Projeksiyonlu OCR (1 Satır)        : {avg_fast_ocr_1:.2f} ms")
    print(f"3. Hızlı Satır Projeksiyonlu OCR (2 Satır Batch)  : {avg_fast_ocr_2:.2f} ms")
    print(f"4. Standart Tam Kare OCR (DBNet + CRNN)           : {avg_full_ocr_1:.2f} ms ({ocr_speedup:.1f}x daha yavaş)")
    print(f"5. CTranslate2 INT8 NMT (Kısa Diyalog, ~6 kelime) : {avg_nmt_short:.2f} ms")
    print(f"6. CTranslate2 INT8 NMT (Orta Diyalog, ~13 kelime): {avg_nmt_med:.2f} ms")
    print(f"7. CTranslate2 INT8 NMT (Çok Cümleli Batch)       : {avg_nmt_multi:.2f} ms")
    print(f"8. LRU RAM Önbellek / Sözlük Yanıt Süresi         : {avg_cache:.4f} ms / {avg_glossary:.4f} ms")
    print("-" * 74)
    print(f"🚀 Uçtan Uca Toplam Gecikme (Yeni Kısa Altyazı)   : {e2e_cold_short:.2f} ms")
    print(f"🚀 Uçtan Uca Toplam Gecikme (Yeni Uzun Altyazı)   : {e2e_cold_med:.2f} ms")
    print(f"⚡ Uçtan Uca Toplam Gecikme (Önbellek / Sözlük)   : {e2e_cached:.2f} ms")
    print(f"🛡️ GPU / VRAM Kullanımı                           : 0 MB (%100 CPU INT8)")
    print("=" * 74)

    out_json = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmark_results.json")
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
