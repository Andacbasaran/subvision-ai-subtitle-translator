"""
SubVision AI — Oyunlar, Diziler, Filmler ve Yayınlar İçin Ultra Hızlı Lokal (EN -> TR) Anlık Altyazı Çevirici
Mimari: CTranslate2 INT8 (Opus-MT EN->TR) + RapidOCR (ONNX CPU) + WDA_EXCLUDEFROMCAPTURE Şeffaf Overlay
"""

import ctypes
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QRect, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ocr_engine import SubtitleOCREngine
from overlay_ui import ROISelectorOverlay, SubtitleOverlayWindow
from translator import LocalEnTrTranslator, get_app_base_dir

APP_TITLE = "SubVision AI — Anlık Ekran Altyazı Çevirici (EN ➔ TR)"
CONFIG_PATH = os.path.join(get_app_base_dir(), "user_settings.json")

# Windows Global Hotkey Sabitleri (Admin yetkisi gerektirmez)
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78


def create_app_icon() -> QIcon:
    """
    Dosya sisteminde ikon olmasa bile yüksek çözünürlüklü vektörel uygulama ikonu üretir.
    """
    ico_path = os.path.join(get_app_base_dir(), "assets", "app_icon.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)

    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    grad = QLinearGradient(0, 0, 64, 64)
    grad.setColorAt(0.0, QColor("#4F46E5"))
    grad.setColorAt(1.0, QColor("#06B6D4"))

    painter.setBrush(grad)
    painter.setPen(QPen(QColor("#38BDF8"), 2))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    # Üstte 'TR' rozeti ve altta altyazı çizgileri
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
    painter.drawText(QRect(4, 8, 56, 28), Qt.AlignmentFlag.AlignCenter, "TR")

    painter.setPen(QPen(QColor("#FACC15"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(14, 43, 50, 43)
    painter.setPen(QPen(QColor("#E2E8F0"), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(20, 51, 44, 51)

    painter.end()
    return QIcon(pix)


class ModelLoaderThread(QThread):
    progress = pyqtSignal(str, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, translator: LocalEnTrTranslator):
        super().__init__()
        self.translator = translator

    def run(self) -> None:
        try:
            self.translator.load(progress_callback=lambda msg, pct: self.progress.emit(msg, pct))
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class BenchmarkWorker(QThread):
    """
    Arayüzü dondurmadan gerçek OCR + CTranslate2 INT8 + Önbellek + Piksel Kilidi
    performans testini çalıştıran iş parçacığı.
    """

    finished_report = pyqtSignal(dict)

    def __init__(self, ocr_engine: SubtitleOCREngine, translator: LocalEnTrTranslator):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.translator = translator

    def run(self) -> None:
        # 1. Sentetik 1080p altyazı şeridi oluştur (960x100)
        canvas = np.zeros((100, 960, 3), dtype=np.uint8)
        canvas[:] = (35, 30, 25)
        text_sample = "We have to find another way out before the storm hits!"
        cv2.putText(
            canvas,
            text_sample,
            (32, 62),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.88,
            (0, 0, 0),
            5,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            text_sample,
            (32, 62),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.88,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        # Piksel Değişim Kilidi hızı (100 iterasyon ortalaması)
        t0 = time.perf_counter()
        gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        for _ in range(100):
            _ = self.ocr_engine._has_frame_changed(gray)
        pixel_lock_ms = ((time.perf_counter() - t0) * 1000.0) / 100.0

        # Hızlı Kontür Maskeli OCR hızı (5 iterasyon ortalaması)
        prev_mode = self.ocr_engine.ocr_mode
        self.ocr_engine.set_mode("fast_mask")
        ocr_times: List[float] = []
        for _ in range(5):
            _, ms = self.ocr_engine.read_image_fast(canvas)
            ocr_times.append(ms)
        self.ocr_engine.set_mode(prev_mode)
        avg_ocr_ms = sum(ocr_times) / max(1, len(ocr_times))

        # CTranslate2 INT8 Soğuk (Uncached) Çeviri Hızı
        test_sentences = [
            "Detective: The signal is coming from inside the abandoned station.",
            "If we don't make a choice right now, everything we built will collapse.",
            "Stay behind me and keep your eyes on the horizon.",
            "Previously on this series, the truth was hidden beneath the city.",
        ]
        nmt_times: List[float] = []
        for s in test_sentences:
            with self.translator._lock:
                self.translator._cache.pop(s.lower(), None)
            _, ms, _ = self.translator.translate_with_metrics(s)
            nmt_times.append(ms)
        avg_nmt_ms = sum(nmt_times) / max(1, len(nmt_times))

        # LRU Cache / Sözlük Hızı (100 iterasyon ortalaması)
        t_c = time.perf_counter()
        for _ in range(100):
            self.translator.translate_with_metrics(test_sentences[0])
        cache_ms = ((time.perf_counter() - t_c) * 1000.0) / 100.0

        report = {
            "pixel_lock_ms": pixel_lock_ms,
            "avg_ocr_ms": avg_ocr_ms,
            "avg_nmt_ms": avg_nmt_ms,
            "cache_ms": cache_ms,
            "total_cold_ms": avg_ocr_ms + avg_nmt_ms,
            "total_cached_ms": avg_ocr_ms + cache_ms,
            "threads": self.translator.cpu_threads,
        }
        self.finished_report.emit(report)


class CaptureTranslateWorker(QThread):
    """
    Arka planda seçili altyazı alanını sabit maksimum hızda (30 FPS / ~33 ms) tarayan,
    piksel değişim kilidi sayesinde sadece yeni altyazı çıktığı anda sıfır gecikmeyle
    OCR ve CTranslate2 INT8 çeviri motorunu tetikleyen iş parçacığı.
    """

    subtitle_updated = pyqtSignal(str, str, float, float, bool)  # en, tr, ocr_ms, tr_ms, cached
    subtitle_cleared = pyqtSignal()
    status_tick = pyqtSignal(str)

    FIXED_SCAN_INTERVAL_SEC = 0.033  # 30 FPS (33 ms)

    def __init__(
        self,
        ocr_engine: SubtitleOCREngine,
        translator: LocalEnTrTranslator,
        roi: Dict[str, int],
    ):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.translator = translator
        self.roi = roi
        self.running = False

    def run(self) -> None:
        self.running = True
        self.ocr_engine.reset_state()

        with mss.mss() as sct:
            while self.running:
                loop_start = time.perf_counter()
                try:
                    capture_box = {
                        "left": self.roi["left"],
                        "top": self.roi["top"],
                        "width": self.roi["width"],
                        "height": self.roi["height"],
                    }
                    status, en_text, ocr_ms = self.ocr_engine.capture_and_read(capture_box, sct)

                    if status == "EMPTY":
                        self.subtitle_cleared.emit()
                    elif status == "NEW_TEXT" and en_text:
                        tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(en_text)
                        if tr_text:
                            self.subtitle_updated.emit(en_text, tr_text, ocr_ms, tr_ms, is_cached)
                except Exception as exc:
                    self.status_tick.emit(f"Yakalama hatası: {exc}")

                elapsed = time.perf_counter() - loop_start
                sleep_time = max(0.008, self.FIXED_SCAN_INTERVAL_SEC - elapsed)
                time.sleep(sleep_time)

    def stop(self) -> None:
        self.running = False
        self.wait(1500)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(860, 780)
        self.resize(940, 820)

        self.settings = self._load_settings()
        self.roi: Dict[str, int] = self.settings.get("roi", self._default_roi())
        self._resume_after_roi = False

        optimal_threads = max(2, min(6, (os.cpu_count() or 4) // 2))
        self.translator = LocalEnTrTranslator(cpu_threads=optimal_threads)

        saved_ocr_mode = self.settings.get("ocr_mode", "hybrid")
        self.ocr_engine = SubtitleOCREngine(
            use_color_mask=(saved_ocr_mode != "full_ocr"),
            ocr_mode=saved_ocr_mode,
        )
        self.worker: Optional[CaptureTranslateWorker] = None
        self.bench_worker: Optional[BenchmarkWorker] = None

        self.overlay = SubtitleOverlayWindow()
        self.roi_selector = ROISelectorOverlay(on_selected=self._on_roi_selected)

        # Oyun, Dizi, Film ve Belgesellerden Gerçekçi Test Diyalogları
        self._sample_idx = 0
        self._samples: List[Tuple[str, str]] = [
            ("🎬 Dizi / Drama", "Detective: Everything we found in that room points to a much bigger conspiracy."),
            ("🎮 Oyun / RPG", "Arthur: Stay close to me, the woods ahead are crawling with bounty hunters."),
            ("🍿 Bilim Kurgu Film", "Commander: If we cross the event horizon, there's no turning back for any of us."),
            ("📺 Belgesel / Yayın", "For centuries, this ancient civilization remained completely hidden beneath the jungle."),
            ("🎮 Aksiyon / Macera", "Hold on tight! I'm gonna take the shortcut through the old tunnel!"),
            ("🎬 Sinema / Gerilim", "We need to talk before they realize what really happened last night."),
        ]

        self._build_ui()
        self._apply_saved_appearance()
        self.overlay.show()
        self.overlay.align_to_roi(self.roi)

        self._register_global_hotkeys()
        self._start_model_loading()

    def _default_roi(self) -> Dict[str, int]:
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        sg = screen.geometry() if screen else None
        sw = sg.width() if sg else 1920
        sh = sg.height() if sg else 1080

        w = int(sw * 0.56)
        h = 105
        x = (sw - w) // 2
        y = sh - h - 65
        return {
            "left": int(x * dpr),
            "top": int(y * dpr),
            "width": int(w * dpr),
            "height": int(h * dpr),
            "qt_left": x,
            "qt_top": y,
            "qt_width": w,
            "qt_height": h,
        }

    def _load_settings(self) -> dict:
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_settings(self) -> None:
        data = {
            "roi": self.roi,
            "font_size": self.slider_font.value(),
            "bg_alpha": self.slider_alpha.value(),
            "text_color": self.combo_color.currentData(),
            "overlay_mode": self.combo_mode.currentData(),
            "ocr_mode": self.combo_ocr_mode.currentData(),
            "show_bilingual": self.chk_bilingual.isChecked(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _create_metric_card(
        self, title: str, initial_val: str, sub_text: str, accent_hex: str
    ) -> Tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setStyleSheet(
            f"""
            QFrame {{
                background-color: #111827;
                border: 1px solid #1E293B;
                border-top: 3px solid {accent_hex};
                border-radius: 10px;
                padding: 8px 10px;
            }}
            """
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(
            "color: #94A3B8; font-size: 8.5pt; font-weight: 700; border: none; background: transparent;"
        )
        lay.addWidget(lbl_title)

        lbl_val = QLabel(initial_val)
        lbl_val.setStyleSheet(
            f"color: {accent_hex}; font-size: 14pt; font-weight: 800; border: none; background: transparent;"
        )
        lay.addWidget(lbl_val)

        lbl_sub = QLabel(sub_text)
        lbl_sub.setStyleSheet(
            "color: #64748B; font-size: 8pt; font-weight: 500; border: none; background: transparent;"
        )
        lay.addWidget(lbl_sub)

        return card, lbl_val, lbl_sub

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#centralWidget {
                background-color: #0B0F19;
                color: #F8FAFC;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QLabel {
                background-color: transparent;
                color: #E2E8F0;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QGroupBox {
                border: 1px solid #1E293B;
                border-radius: 10px;
                margin-top: 12px;
                padding: 16px 14px 12px 14px;
                background-color: #111827;
                font-weight: 700;
                font-size: 9.8pt;
                color: #E2E8F0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
                color: #38BDF8;
                background-color: #111827;
            }
            QPushButton {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 9px 14px;
                font-size: 10pt;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
            QPushButton:disabled {
                background-color: #0F172A;
                color: #475569;
                border-color: #1E293B;
            }
            QComboBox {
                background-color: #0B0F19;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                min-height: 24px;
                color: #F8FAFC;
                font-size: 9.3pt;
            }
            QComboBox:hover {
                border-color: #38BDF8;
            }
            QComboBox QAbstractItemView {
                background-color: #111827;
                color: #F8FAFC;
                selection-background-color: #2563EB;
                border: 1px solid #334155;
            }
            QSlider {
                background-color: transparent;
            }
            QSlider::groove:horizontal {
                border: 1px solid #1E293B;
                height: 6px;
                background: #0B0F19;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #38BDF8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #F8FAFC;
                border: 2px solid #0284C7;
                width: 16px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QCheckBox {
                background-color: transparent;
                color: #CBD5E1;
                font-size: 9.2pt;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 17px;
                height: 17px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #0B0F19;
            }
            QCheckBox::indicator:checked {
                background-color: #2563EB;
                border-color: #60A5FA;
            }
            QProgressBar {
                border: 1px solid #1E293B;
                border-radius: 6px;
                text-align: center;
                background-color: #0B0F19;
                height: 18px;
                color: #F8FAFC;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #10B981);
                border-radius: 5px;
            }
            QListWidget {
                background-color: #0B0F19;
                border: 1px solid #1E293B;
                border-radius: 8px;
                color: #CBD5E1;
                font-size: 9.2pt;
                padding: 4px;
            }
            QListWidget::item {
                padding: 5px 8px;
                border-bottom: 1px solid #111827;
            }
            QListWidget::item:selected {
                background-color: #1E293B;
                color: #FACC15;
                border-radius: 4px;
            }
            """
        )

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(16, 14, 16, 14)

        # 1. ÜST BAŞLIK & MODEL DURUM KARTI (Hero Header)
        header_frame = QFrame()
        header_frame.setStyleSheet(
            """
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #111827, stop:0.6 #1E293B, stop:1 #0F172A);
                border-radius: 12px;
                padding: 10px 14px;
                border: 1px solid #334155;
            }
            """
        )
        header_v = QVBoxLayout(header_frame)
        header_v.setContentsMargins(6, 4, 6, 4)
        header_v.setSpacing(6)

        top_bar = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title_lbl = QLabel("⚡ SubVision AI — Anlık Ekran Altyazı Çevirici")
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Black))
        title_lbl.setStyleSheet("color: #F8FAFC; border: none; background: transparent;")
        title_col.addWidget(title_lbl)

        sub_lbl = QLabel(
            "Oyunlar, Diziler, Filmler ve Yayınlar İçin Ultra Düşük Gecikmeli Lokal Yapay Zeka (EN ➔ TR)"
        )
        sub_lbl.setStyleSheet("color: #94A3B8; font-size: 8.8pt; border: none; background: transparent;")
        title_col.addWidget(sub_lbl)
        top_bar.addLayout(title_col, stretch=1)

        # Sağ Üst Rozetler
        badge_col = QVBoxLayout()
        badge_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        badge_col.setSpacing(4)

        hw_badge = QLabel("🧠 CTranslate2 INT8  •  ⚡ RapidOCR ONNX  •  🛡️ 0 MB VRAM")
        hw_badge.setStyleSheet(
            "color: #38BDF8; background-color: #0B0F19; border: 1px solid #1E293B; border-radius: 6px; padding: 3px 10px; font-size: 8.5pt; font-weight: 700;"
        )
        badge_col.addWidget(hw_badge, alignment=Qt.AlignmentFlag.AlignRight)

        self.lbl_model_status = QLabel("⏳ Lokal Yapay Zeka Modeli Kontrol Ediliyor...")
        self.lbl_model_status.setStyleSheet(
            "color: #FACC15; font-size: 9pt; font-weight: 700; border: none; background: transparent;"
        )
        badge_col.addWidget(self.lbl_model_status, alignment=Qt.AlignmentFlag.AlignRight)
        top_bar.addLayout(badge_col)

        header_v.addLayout(top_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        header_v.addWidget(self.progress_bar)

        main_layout.addWidget(header_frame)

        # 2. TELEMETRİ & PERFORMANS KARTLARI (4 KPI Cards)
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        card_ocr, self.lbl_kpi_ocr, self.lbl_kpi_ocr_sub = self._create_metric_card(
            "OCR YAKALAMA SÜRESİ",
            "— ms",
            "RapidOCR + Piksel Kilidi",
            "#38BDF8",
        )
        card_nmt, self.lbl_kpi_nmt, self.lbl_kpi_nmt_sub = self._create_metric_card(
            "NMT ÇEVİRİ SÜRESİ",
            "— ms",
            f"Opus-MT INT8 ({self.translator.cpu_threads} Thread)",
            "#FACC15",
        )
        card_tot, self.lbl_kpi_total, self.lbl_kpi_total_sub = self._create_metric_card(
            "TOPLAM UÇTAN UCA",
            "— ms",
            "Yakalama + Okuma + Çeviri",
            "#4ADE80",
        )
        card_stat, self.lbl_kpi_stats, self.lbl_kpi_stats_sub = self._create_metric_card(
            "OTURUM & TARAMA ALANI",
            "0 Çeviri",
            f"ROI: {self.roi['width']}×{self.roi['height']} px @ 30 FPS",
            "#A78BFA",
        )

        kpi_row.addWidget(card_ocr)
        kpi_row.addWidget(card_nmt)
        kpi_row.addWidget(card_tot)
        kpi_row.addWidget(card_stat)
        main_layout.addLayout(kpi_row)

        # 3. ANA KONTROL BUTONLARI
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_select_roi = QPushButton("🎯 1. Altyazı Alanını Seç (F7)")
        self.btn_select_roi.setStyleSheet(
            "QPushButton { background-color: #2563EB; border-color: #3B82F6; } QPushButton:hover { background-color: #1D4ED8; }"
        )
        self.btn_select_roi.clicked.connect(self.open_roi_selector)
        btn_row.addWidget(self.btn_select_roi, stretch=3)

        self.btn_toggle = QPushButton("▶️ 2. Anlık Çeviriyi Başlat (F8)")
        self.btn_toggle.setEnabled(False)
        self.btn_toggle.setStyleSheet(
            "QPushButton { background-color: #16A34A; border-color: #22C55E; } QPushButton:hover { background-color: #15803D; }"
        )
        self.btn_toggle.clicked.connect(self.toggle_translation)
        btn_row.addWidget(self.btn_toggle, stretch=3)

        self.btn_test = QPushButton("🧪 Sahne Testi (F9)")
        self.btn_test.setEnabled(False)
        self.btn_test.setStyleSheet(
            "QPushButton { background-color: #1E293B; border-color: #475569; } QPushButton:hover { background-color: #334155; }"
        )
        self.btn_test.clicked.connect(self.run_sample_test)
        btn_row.addWidget(self.btn_test, stretch=2)

        self.btn_benchmark = QPushButton("📊 Benchmark Testi")
        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.setStyleSheet(
            "QPushButton { background-color: #4F46E5; border-color: #6366F1; } QPushButton:hover { background-color: #4338CA; }"
        )
        self.btn_benchmark.clicked.connect(self.run_benchmark_suite)
        btn_row.addWidget(self.btn_benchmark, stretch=2)

        main_layout.addLayout(btn_row)

        # 4. SAHNE PROFİLİ & ALTYAZI KATMAN (OVERLAY) AYARLARI
        grp_settings = QGroupBox("Sahne Algılama Profili && Şeffaf Altyazı Katmanı Ayarları")
        grid = QGridLayout(grp_settings)
        grid.setSpacing(10)

        # Algılama / İçerik Modu
        grid.addWidget(QLabel("İçerik & OCR Modu:"), 0, 0)
        self.combo_ocr_mode = QComboBox()
        self.combo_ocr_mode.addItem(
            "🎬 Oyun, Dizi & Film (Akıllı Hibrit Filtre)", "hybrid"
        )
        self.combo_ocr_mode.addItem(
            "⚡ Kontürlü Altyazı Modu (Maksimum Hız)", "fast_mask"
        )
        self.combo_ocr_mode.addItem(
            "🖥️ Genel Ekran & Video (Tam Kare OCR)", "full_ocr"
        )
        self.combo_ocr_mode.currentIndexChanged.connect(self._on_ocr_mode_changed)
        grid.addWidget(self.combo_ocr_mode, 0, 1)

        # Konum Modu
        grid.addWidget(QLabel("Altyazı Konumu:"), 0, 2)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Orijinal Altyazının Üstünü Kapat (Önerilen)", "cover")
        self.combo_mode.addItem("Orijinal Altyazının Hemen Üstünde Göster", "above")
        self.combo_mode.currentIndexChanged.connect(self._on_appearance_changed)
        grid.addWidget(self.combo_mode, 0, 3)

        # Yazı Boyutu
        self.lbl_font_val = QLabel(f"Yazı Boyutu ({self.settings.get('font_size', 21)} pt):")
        grid.addWidget(self.lbl_font_val, 1, 0)
        self.slider_font = QSlider(Qt.Orientation.Horizontal)
        self.slider_font.setRange(14, 36)
        self.slider_font.setValue(self.settings.get("font_size", 21))
        self.slider_font.valueChanged.connect(self._on_appearance_changed)
        grid.addWidget(self.slider_font, 1, 1)

        # Yazı Rengi
        grid.addWidget(QLabel("Altyazı Rengi:"), 1, 2)
        self.combo_color = QComboBox()
        self.combo_color.addItem("Sinema Beyazı (#FFFFFF)", "#FFFFFF")
        self.combo_color.addItem("Netflix / Sinema Sarısı (#FACC15)", "#FACC15")
        self.combo_color.addItem("Cyberpunk Turkuaz (#38BDF8)", "#38BDF8")
        self.combo_color.addItem("Zümrüt Yeşili (#4ADE80)", "#4ADE80")
        self.combo_color.currentIndexChanged.connect(self._on_appearance_changed)
        grid.addWidget(self.combo_color, 1, 3)

        # Arka Plan Koyuluğu
        init_alpha = self.settings.get("bg_alpha", 225)
        self.lbl_alpha_val = QLabel(f"Arka Plan Opaklığı (%{int(init_alpha / 255 * 100)}):")
        grid.addWidget(self.lbl_alpha_val, 2, 0)
        self.slider_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_alpha.setRange(90, 250)
        self.slider_alpha.setValue(init_alpha)
        self.slider_alpha.valueChanged.connect(self._on_appearance_changed)
        grid.addWidget(self.slider_alpha, 2, 1)

        # Çift Dilli Altyazı Seçeneği (Dizi/Film izleyicileri için TR + EN)
        self.chk_bilingual = QCheckBox(
            "Çift Dilli Altyazı (Türkçe çevirinin üstünde İngilizce orijinalini de göster)"
        )
        self.chk_bilingual.setChecked(self.settings.get("show_bilingual", False))
        self.chk_bilingual.toggled.connect(self._on_appearance_changed)
        grid.addWidget(self.chk_bilingual, 2, 2, 1, 2)

        # Hizalama Çerçevesi Göster
        self.chk_guide = QCheckBox(
            "Ekranda Türkçe Altyazı Kutusunun Sınırlarını Göster (Hizalama Kılavuzu)"
        )
        self.chk_guide.setChecked(False)
        self.chk_guide.toggled.connect(self.overlay.set_guide_border)
        grid.addWidget(self.chk_guide, 3, 0, 1, 4)

        main_layout.addWidget(grp_settings)

        # 5. CANLI YAKALAMA MONİTÖRÜ & ÇEVİRİ GEÇMİŞİ
        grp_live = QGroupBox("Canlı Yakalama Monitörü && Diyalog Geçmişi")
        live_layout = QVBoxLayout(grp_live)
        live_layout.setSpacing(6)

        # EN & TR Canlı Kartları
        en_header = QHBoxLayout()
        lbl_en_title = QLabel("Yakalanan İngilizce Altyazı (EN):")
        lbl_en_title.setStyleSheet("color: #94A3B8; font-size: 9pt; font-weight: 600;")
        en_header.addWidget(lbl_en_title)
        self.lbl_scene_tag = QLabel("Mod: Canlı Ekran Yakalama")
        self.lbl_scene_tag.setStyleSheet("color: #38BDF8; font-size: 8.5pt; font-weight: 600;")
        en_header.addWidget(self.lbl_scene_tag, alignment=Qt.AlignmentFlag.AlignRight)
        live_layout.addLayout(en_header)

        self.lbl_en_preview = QLabel("Henüz altyazı yakalanmadı. (F7 ile bölge seçip F8 ile başlatın veya F9 ile test edin)")
        self.lbl_en_preview.setWordWrap(True)
        self.lbl_en_preview.setMinimumHeight(38)
        self.lbl_en_preview.setStyleSheet(
            "background-color: #0B0F19; border: 1px solid #1E293B; padding: 8px 12px; border-radius: 7px; color: #E2E8F0; font-size: 10.2pt;"
        )
        live_layout.addWidget(self.lbl_en_preview)

        tr_header = QHBoxLayout()
        lbl_tr_title = QLabel("Anlık Türkçe Çeviri (TR):")
        lbl_tr_title.setStyleSheet("color: #94A3B8; font-size: 9pt; font-weight: 600;")
        tr_header.addWidget(lbl_tr_title)

        btn_copy = QPushButton("📋 Çeviriyi Kopyala")
        btn_copy.setStyleSheet(
            "QPushButton { background-color: #1E293B; padding: 4px 12px; font-size: 8.5pt; border-radius: 5px; } QPushButton:hover { background-color: #334155; }"
        )
        btn_copy.clicked.connect(self._copy_current_translation)
        tr_header.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignRight)
        live_layout.addLayout(tr_header)

        self.lbl_tr_preview = QLabel("Çeviri bekleniyor...")
        self.lbl_tr_preview.setWordWrap(True)
        self.lbl_tr_preview.setMinimumHeight(40)
        self.lbl_tr_preview.setStyleSheet(
            "background-color: #0B0F19; border: 1px solid #334155; padding: 8px 12px; border-radius: 7px; color: #FACC15; font-size: 11.2pt; font-weight: bold;"
        )
        live_layout.addWidget(self.lbl_tr_preview)

        # Son Çeviriler Geçmişi Başlığı
        hist_header = QHBoxLayout()
        lbl_hist = QLabel("📜 Son Çevrilen Altyazı Geçmişi:")
        lbl_hist.setStyleSheet("color: #94A3B8; font-size: 8.8pt; font-weight: 600;")
        hist_header.addWidget(lbl_hist)

        btn_clear_hist = QPushButton("Geçmişi Temizle")
        btn_clear_hist.setStyleSheet(
            "QPushButton { background-color: transparent; color: #64748B; border: none; padding: 2px 6px; font-size: 8.5pt; } QPushButton:hover { color: #F87171; }"
        )
        btn_clear_hist.clicked.connect(lambda: self.list_history.clear())
        hist_header.addWidget(btn_clear_hist, alignment=Qt.AlignmentFlag.AlignRight)
        live_layout.addLayout(hist_header)

        self.list_history = QListWidget()
        self.list_history.setMinimumHeight(92)
        live_layout.addWidget(self.list_history, stretch=1)

        main_layout.addWidget(grp_live, stretch=1)

        # 6. ALT BİLGİ NOTU
        footer = QLabel(
            "💡 İpucu: Oyunlarda 'Çerçevesiz Pencere (Borderless Windowed)' modunu kullanın; "
            "Netflix, YouTube, Prime Video, VLC ve Twitch gibi tüm dizi/film oynatıcılarda doğrudan çalışır. "
            "Global Kısayollar: F7 (Alan Seç)  •  F8 (Başlat/Durdur)  •  F9 (Örnek Sahne Testi)"
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #64748B; font-size: 8.6pt;")
        main_layout.addWidget(footer)

    def _apply_saved_appearance(self) -> None:
        saved_color = self.settings.get("text_color", "#FFFFFF")
        idx_c = self.combo_color.findData(saved_color)
        if idx_c >= 0:
            self.combo_color.setCurrentIndex(idx_c)

        saved_mode = self.settings.get("overlay_mode", "cover")
        idx_m = self.combo_mode.findData(saved_mode)
        if idx_m >= 0:
            self.combo_mode.setCurrentIndex(idx_m)

        saved_ocr = self.settings.get("ocr_mode", "hybrid")
        idx_o = self.combo_ocr_mode.findData(saved_ocr)
        if idx_o >= 0:
            self.combo_ocr_mode.setCurrentIndex(idx_o)

        self._on_appearance_changed()

    def _start_model_loading(self) -> None:
        self.loader_thread = ModelLoaderThread(self.translator)
        self.loader_thread.progress.connect(self._on_model_progress)
        self.loader_thread.finished_ok.connect(self._on_model_ready)
        self.loader_thread.failed.connect(self._on_model_failed)
        self.loader_thread.start()

    def _on_model_progress(self, msg: str, pct: int) -> None:
        self.lbl_model_status.setText(msg)
        self.progress_bar.setValue(pct)

    def _on_model_ready(self) -> None:
        self.lbl_model_status.setText("● MODEL HAZIR: Opus-MT Big (EN ➔ TR | INT8 CPU)")
        self.lbl_model_status.setStyleSheet(
            "color: #4ADE80; font-weight: 800; font-size: 9pt; border: none; background: transparent;"
        )
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.btn_toggle.setEnabled(True)
        self.btn_test.setEnabled(True)
        self.btn_benchmark.setEnabled(True)

    def _on_model_failed(self, err: str) -> None:
        self.lbl_model_status.setText(f"❌ Model yükleme hatası: {err}")
        self.lbl_model_status.setStyleSheet("color: #F87171; font-weight: bold;")

    def open_roi_selector(self) -> None:
        was_running = self.worker is not None and self.worker.running
        self._resume_after_roi = was_running
        if was_running:
            self.toggle_translation()
        self.roi_selector.show_selector()

    def _on_roi_selected(self, new_roi: Dict[str, int]) -> None:
        self.roi = new_roi
        self.overlay.align_to_roi(self.roi)
        self._update_session_kpi()
        self._save_settings()
        if self._resume_after_roi and self.translator.is_ready:
            self._resume_after_roi = False
            self.toggle_translation()
        else:
            self.overlay.set_subtitle(
                "✅ Altyazı alanı seçildi! Çeviriyi başlatmak için F8 tuşuna basın."
            )

    def _on_appearance_changed(self) -> None:
        f_size = self.slider_font.value()
        alpha = self.slider_alpha.value()
        self.lbl_font_val.setText(f"Yazı Boyutu ({f_size} pt):")
        self.lbl_alpha_val.setText(f"Arka Plan Opaklığı (%{int(alpha / 255 * 100)}):")

        self.overlay.update_appearance(
            font_size=f_size,
            text_color=self.combo_color.currentData(),
            bg_alpha=alpha,
            overlay_mode=self.combo_mode.currentData(),
            show_bilingual=self.chk_bilingual.isChecked(),
        )
        self.overlay.align_to_roi(self.roi)
        self._save_settings()

    def _on_ocr_mode_changed(self) -> None:
        mode = self.combo_ocr_mode.currentData()
        self.ocr_engine.set_mode(mode)
        self._save_settings()

    def _copy_current_translation(self) -> None:
        tr = self.lbl_tr_preview.text().strip()
        if tr and tr != "Çeviri bekleniyor...":
            QGuiApplication.clipboard().setText(tr)

    def _update_session_kpi(self) -> None:
        req = self.translator.total_requests
        hits = self.translator.cache_hits
        hit_pct = int((hits / req) * 100) if req > 0 else 0
        self.lbl_kpi_stats.setText(f"{req} Çeviri")
        self.lbl_kpi_stats_sub.setText(
            f"Önbellek: %{hit_pct}  |  {self.roi['width']}×{self.roi['height']} px"
        )

    def toggle_translation(self) -> None:
        if not self.translator.is_ready:
            return

        if self.worker and self.worker.running:
            self.worker.stop()
            self.worker = None
            self.btn_toggle.setText("▶️ 2. Anlık Çeviriyi Başlat (F8)")
            self.btn_toggle.setStyleSheet(
                "QPushButton { background-color: #16A34A; border-color: #22C55E; } QPushButton:hover { background-color: #15803D; }"
            )
            self.lbl_model_status.setText("● MODEL HAZIR: Opus-MT Big (EN ➔ TR | INT8 CPU)")
            self.overlay.set_subtitle("")
        else:
            self.overlay.align_to_roi(self.roi)
            self.overlay.set_subtitle("")
            self.lbl_scene_tag.setText("Mod: Canlı Ekran Yakalama (30 FPS)")
            self.worker = CaptureTranslateWorker(
                ocr_engine=self.ocr_engine,
                translator=self.translator,
                roi=self.roi,
            )
            self.worker.subtitle_updated.connect(self._on_subtitle_updated)
            self.worker.subtitle_cleared.connect(self._on_subtitle_cleared)
            self.worker.status_tick.connect(lambda msg: self.lbl_kpi_total_sub.setText(msg))
            self.worker.start()

            self.lbl_model_status.setText("🟢 CANLI TARAMA AKTİF (30 FPS / 33 ms)")
            self.btn_toggle.setText("⏹️ Çeviriyi Durdur (F8)")
            self.btn_toggle.setStyleSheet(
                "QPushButton { background-color: #DC2626; border-color: #EF4444; } QPushButton:hover { background-color: #B91C1C; }"
            )

    def _on_subtitle_updated(
        self, en_text: str, tr_text: str, ocr_ms: float, tr_ms: float, is_cached: bool
    ) -> None:
        self.overlay.set_subtitle(tr_text, en_text)
        self.lbl_en_preview.setText(en_text)
        self.lbl_tr_preview.setText(tr_text)

        total_ms = ocr_ms + tr_ms
        self.lbl_kpi_ocr.setText(f"{ocr_ms:.1f} ms")
        self.lbl_kpi_nmt.setText(f"{tr_ms:.2f} ms" if is_cached else f"{tr_ms:.1f} ms")
        self.lbl_kpi_nmt_sub.setText(
            "⚡ RAM Önbellek / Sözlük Hit" if is_cached else f"🧠 CTranslate2 INT8 ({self.translator.cpu_threads} Thread)"
        )
        self.lbl_kpi_total.setText(f"{total_ms:.1f} ms")
        self.lbl_kpi_total_sub.setText("⚡ Anlık Yanıt" if total_ms < 85 else "✅ Gerçek Zamanlı")
        self._update_session_kpi()

        stamp = datetime.now().strftime("%H:%M:%S")
        tag = "⚡" if is_cached else "🧠"
        entry = f"[{stamp}] ({total_ms:.1f} ms {tag})  {en_text}  ➔  {tr_text}"
        self.list_history.insertItem(0, entry)
        if self.list_history.count() > 30:
            self.list_history.takeItem(self.list_history.count() - 1)

    def _on_subtitle_cleared(self) -> None:
        self.overlay.set_subtitle("")

    def run_sample_test(self) -> None:
        if not self.translator.is_ready:
            return
        category, sample_en = self._samples[self._sample_idx % len(self._samples)]
        self._sample_idx += 1
        self.lbl_scene_tag.setText(f"Örnek Sahne: {category}")
        tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(sample_en)
        self._on_subtitle_updated(sample_en, tr_text, 0.0, tr_ms, is_cached)

    def run_benchmark_suite(self) -> None:
        if not self.translator.is_ready:
            return
        if self.bench_worker and self.bench_worker.isRunning():
            return

        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.setText("⏳ Ölçülüyor...")
        self.bench_worker = BenchmarkWorker(self.ocr_engine, self.translator)
        self.bench_worker.finished_report.connect(self._on_benchmark_finished)
        self.bench_worker.start()

    def _on_benchmark_finished(self, rep: dict) -> None:
        self.btn_benchmark.setEnabled(True)
        self.btn_benchmark.setText("📊 Benchmark Testi")

        self.lbl_kpi_ocr.setText(f"{rep['avg_ocr_ms']:.1f} ms")
        self.lbl_kpi_nmt.setText(f"{rep['avg_nmt_ms']:.1f} ms")
        self.lbl_kpi_total.setText(f"{rep['total_cold_ms']:.1f} ms")
        self.lbl_kpi_total_sub.setText(f"Önbellekli: {rep['total_cached_ms']:.1f} ms")

        msg = (
            f"⚡ SubVision AI — Donanım Performans Testi Sonuçları\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Piksel Değişim Kilidi (Boşta Kare Kontrolü):  {rep['pixel_lock_ms']:.3f} ms\n"
            f"• Hızlı Satır Projeksiyonlu OCR (RapidOCR ONNX):  {rep['avg_ocr_ms']:.1f} ms\n"
            f"• CTranslate2 INT8 NMT Çeviri ({rep['threads']} CPU Thread):  {rep['avg_nmt_ms']:.1f} ms\n"
            f"• LRU RAM Önbellek / Kalıp Sözlüğü Yanıtı:  {rep['cache_ms']:.3f} ms\n\n"
            f"🚀 Uçtan Uca Toplam Gecikme (Yeni Cümle):  {rep['total_cold_ms']:.1f} ms\n"
            f"⚡ Uçtan Uca Toplam Gecikme (Önbellek Hit):  {rep['total_cached_ms']:.1f} ms\n"
            f"🛡️ Ekran Kartı (GPU / VRAM) Tüketimi:  0 MB (%100 CPU)"
        )
        QMessageBox.information(self, "Performans Benchmark Raporu", msg)

    def _register_global_hotkeys(self) -> None:
        """
        Oyun veya tam ekran dizi/film izlerken çalışan, admin yetkisi gerektirmeyen global kısayol dinleyicisi (F7, F8, F9).
        """
        self._key_states = {VK_F7: False, VK_F8: False, VK_F9: False}
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setInterval(45)
        self._hotkey_timer.timeout.connect(self._poll_global_hotkeys)
        self._hotkey_timer.start()

    def _poll_global_hotkeys(self) -> None:
        try:
            for vk, callback in (
                (VK_F7, self.open_roi_selector),
                (VK_F8, self.toggle_translation),
                (VK_F9, self.run_sample_test),
            ):
                is_down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
                if is_down and not self._key_states.get(vk, False):
                    self._key_states[vk] = True
                    callback()
                elif not is_down:
                    self._key_states[vk] = False
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        if hasattr(self, "_hotkey_timer"):
            self._hotkey_timer.stop()
        if hasattr(self, "loader_thread") and self.loader_thread.isRunning():
            self.loader_thread.wait(2000)
        if self.bench_worker and self.bench_worker.isRunning():
            self.bench_worker.wait(2000)
        if self.worker and self.worker.running:
            self.worker.stop()
        self.overlay.close()
        self.roi_selector.close()
        super().closeEvent(event)


def main():
    # Aynı anda birden fazla kopyanın açılıp çakışmasını engelle (Single-Instance Mutex)
    mutex_name = "SubVisionAI_TR_Subtitle_SingleInstance_Mutex_v2"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = ctypes.windll.user32.FindWindowW(None, APP_TITLE)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        sys.exit(0)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    ret = app.exec()
    if mutex:
        ctypes.windll.kernel32.CloseHandle(mutex)
    sys.exit(ret)


if __name__ == "__main__":
    main()
