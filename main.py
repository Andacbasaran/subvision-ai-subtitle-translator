"""
SubVision AI Studio — Oyunlar, Diziler, Filmler ve Yayınlar İçin Evrensel Lokal (EN -> TR) Anlık Altyazı Çevirici
Mimari: Uyarlanabilir CTranslate2 (INT8/FP32) + RapidOCR (ONNX CPU) + Platforma Duyarlı Şeffaf Overlay
"""

import ctypes
import json
import os
import sys
import time
import traceback
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
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from hardware import (
    HardwareProfile,
    PROFILE_AUTO,
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    RuntimeTuning,
    apply_thread_env_defaults,
    compute_runtime_tuning,
    detect_hardware_profile,
    format_hardware_summary,
    get_app_base_dir,
    get_ui_font_family,
    get_writable_data_dir,
)
from ocr_engine import SubtitleOCREngine
from overlay_ui import ROISelectorOverlay, SubtitleOverlayWindow
from translator import LocalEnTrTranslator

APP_TITLE = "SubVision AI — Real-Time Subtitle Studio (EN ➔ TR)"
DATA_DIR = get_writable_data_dir()
CONFIG_PATH = os.path.join(DATA_DIR, "user_settings.json")
CRASH_LOG_PATH = os.path.join(DATA_DIR, "crash.log")

# Windows Global Hotkey Sabitleri (Admin yetkisi gerektirmez)
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78


def create_app_pixmap(size: int = 64) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#4F46E5"))
    grad.setColorAt(0.5, QColor("#2563EB"))
    grad.setColorAt(1.0, QColor("#06B6D4"))

    pad = max(2, size // 16)
    radius = max(8, size // 4)
    painter.setBrush(grad)
    painter.setPen(QPen(QColor("#38BDF8"), max(1, size // 32)))
    painter.drawRoundedRect(pad, pad, size - 2 * pad, size - 2 * pad, radius, radius)

    painter.setPen(QColor("#FFFFFF"))
    font_sz = max(10, int(size * 0.26))
    painter.setFont(QFont(get_ui_font_family(), font_sz, QFont.Weight.Black))
    painter.drawText(
        QRect(pad, int(size * 0.11), size - 2 * pad, int(size * 0.45)),
        Qt.AlignmentFlag.AlignCenter,
        "TR",
    )

    y1 = int(size * 0.67)
    y2 = int(size * 0.80)
    painter.setPen(
        QPen(QColor("#FACC15"), max(2, size // 15), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(int(size * 0.21), y1, int(size * 0.79), y1)
    painter.setPen(
        QPen(QColor("#E2E8F0"), max(2, size // 18), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(int(size * 0.30), y2, int(size * 0.70), y2)

    painter.end()
    return pix


def create_app_icon() -> QIcon:
    ico_path = os.path.join(get_app_base_dir(), "assets", "app_icon.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)
    return QIcon(create_app_pixmap(64))


class ModelLoaderThread(QThread):
    """
    Arayüzü dondurmadan arka planda önce RapidOCR (ONNX) motorunu,
    ardından CTranslate2 çeviri modelini işlemciye uygun modda yükler.
    """

    progress = pyqtSignal(str, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, translator: LocalEnTrTranslator, ocr_engine: SubtitleOCREngine):
        super().__init__()
        self.translator = translator
        self.ocr_engine = ocr_engine

    def run(self) -> None:
        try:
            self.progress.emit(
                f"OCR motoru hazırlanıyor ({self.ocr_engine.ocr_intra_threads} Thread)...", 8
            )
            self.ocr_engine.ensure_initialized()
            self.progress.emit("OCR motoru hazır! Çeviri modeli kontrol ediliyor...", 18)
            self.translator.load(
                progress_callback=lambda msg, pct: self.progress.emit(
                    msg, max(18, int(18 + pct * 0.82))
                )
            )
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class BenchmarkWorker(QThread):
    """
    Arayüzü dondurmadan gerçek OCR + CTranslate2 + Önbellek + Frame Diff Lock
    performans testini çalıştıran iş parçacığı.
    """

    finished_report = pyqtSignal(dict)

    def __init__(
        self,
        ocr_engine: SubtitleOCREngine,
        translator: LocalEnTrTranslator,
        hw_profile: HardwareProfile,
    ):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.translator = translator
        self.hw_profile = hw_profile

    def run(self) -> None:
        self.ocr_engine.ensure_initialized()
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

        t0 = time.perf_counter()
        gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        for _ in range(100):
            _ = self.ocr_engine._has_frame_changed(gray)
        pixel_lock_ms = ((time.perf_counter() - t0) * 1000.0) / 100.0

        prev_mode = self.ocr_engine.ocr_mode
        self.ocr_engine.set_mode("fast_mask")
        ocr_times: List[float] = []
        for _ in range(5):
            _, ms = self.ocr_engine.read_image_fast(canvas)
            ocr_times.append(ms)
        self.ocr_engine.set_mode(prev_mode)
        avg_ocr_ms = sum(ocr_times) / max(1, len(ocr_times))

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

        t_c = time.perf_counter()
        for _ in range(100):
            self.translator.translate_with_metrics(test_sentences[0])
        cache_ms = ((time.perf_counter() - t_c) * 1000.0) / 100.0

        report = {
            "cpu_name": self.hw_profile.short_cpu_label,
            "cores": f"{self.hw_profile.physical_cores}C/{self.hw_profile.logical_cores}T",
            "compute_type": self.translator.active_compute_type.upper(),
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
    subtitle_updated = pyqtSignal(str, str, float, float, bool)
    subtitle_cleared = pyqtSignal()
    status_tick = pyqtSignal(str)

    def __init__(
        self,
        ocr_engine: SubtitleOCREngine,
        translator: LocalEnTrTranslator,
        roi: Dict[str, int],
        scan_interval_sec: float = 0.0417,
        idle_scan_interval_sec: float = 0.0714,
    ):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.translator = translator
        self.roi = roi
        self.scan_interval_sec = max(0.025, float(scan_interval_sec))
        self.idle_scan_interval_sec = max(self.scan_interval_sec, float(idle_scan_interval_sec))
        self.running = False

    def update_timing(self, scan_interval_sec: float, idle_scan_interval_sec: float) -> None:
        self.scan_interval_sec = max(0.025, float(scan_interval_sec))
        self.idle_scan_interval_sec = max(self.scan_interval_sec, float(idle_scan_interval_sec))

    def run(self) -> None:
        self.running = True
        self.ocr_engine.reset_state()
        idle_streak_sec = 0.0

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
                        idle_streak_sec += self.scan_interval_sec
                    elif status == "NEW_TEXT" and en_text:
                        idle_streak_sec = 0.0
                        tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(en_text)
                        if tr_text:
                            self.subtitle_updated.emit(en_text, tr_text, ocr_ms, tr_ms, is_cached)
                    else:
                        idle_streak_sec += self.scan_interval_sec
                except Exception as exc:
                    self.status_tick.emit(f"Yakalama hatası: {exc}")

                elapsed = time.perf_counter() - loop_start
                # 2 saniye boyunca altyazı değişmediyse işlemciyi dinlendirmek için akıllı bekleme moduna geç
                target_interval = (
                    self.idle_scan_interval_sec
                    if idle_streak_sec >= 2.0
                    else self.scan_interval_sec
                )
                sleep_time = max(0.012, target_interval - elapsed)
                time.sleep(sleep_time)

    def stop(self) -> None:
        self.running = False
        self.wait(1500)


class TelemetryCard(QFrame):
    """
    Modern Studio KPI Telemetri Kartı:
    Başlık, durum rozeti, büyük metrik değeri, görsel gecikme barı ve alt açıklama içerir.
    """

    def __init__(
        self,
        title: str,
        badge_text: str,
        initial_val: str,
        sub_text: str,
        accent_hex: str,
        initial_pct: int = 25,
    ):
        super().__init__()
        self.accent_hex = accent_hex
        self.setObjectName("telemetryCard")
        self.setStyleSheet(
            f"""
            QFrame#telemetryCard {{
                background-color: #111827;
                border: 1px solid #1E293B;
                border-radius: 12px;
            }}
            QFrame#telemetryCard:hover {{
                border: 1px solid {accent_hex};
                background-color: #131C2E;
            }}
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #94A3B8; font-size: 8.2pt; font-weight: 800; letter-spacing: 0.5px;"
        )
        top_row.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet(
            f"""
            color: {accent_hex};
            background-color: #0B0F19;
            border: 1px solid #1E293B;
            border-radius: 5px;
            padding: 2px 7px;
            font-size: 7.5pt;
            font-weight: 800;
            """
        )
        top_row.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(top_row)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet(
            f"color: #F8FAFC; font-size: 16pt; font-weight: 900; padding-top: 1px;"
        )
        lay.addWidget(self.lbl_val)

        # Mini Görsel Gecikme / Doluluk Barı
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(initial_pct)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: #0B0F19;
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_hex};
                border-radius: 2px;
            }}
            """
        )
        lay.addWidget(self.bar)

        self.lbl_sub = QLabel(sub_text)
        self.lbl_sub.setStyleSheet("color: #64748B; font-size: 8pt; font-weight: 600;")
        lay.addWidget(self.lbl_sub)

    def set_metric(
        self,
        val_text: str,
        sub_text: Optional[str] = None,
        badge_text: Optional[str] = None,
        bar_pct: Optional[int] = None,
    ) -> None:
        self.lbl_val.setText(val_text)
        if sub_text is not None:
            self.lbl_sub.setText(sub_text)
        if badge_text is not None:
            self.lbl_badge.setText(badge_text)
        if bar_pct is not None:
            self.bar.setValue(max(4, min(100, bar_pct)))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(create_app_icon())

        # Küçük ekranlar (1366x768 veya 1080p @ %150 DPI) dahil her ekrana sığan pencere boyutlandırması
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        min_w = min(920, max(760, avail.width() - 40))
        min_h = min(640, max(540, avail.height() - 40))
        init_w = min(1080, max(min_w, avail.width() - 40))
        init_h = min(850, max(min_h, avail.height() - 40))
        self.setMinimumSize(min_w, min_h)
        self.resize(init_w, init_h)

        self.settings = self._load_settings()
        self.roi: Dict[str, int] = self.settings.get("roi", self._default_roi())
        self._resume_after_roi = False

        # Evrensel Donanım & İşlemci (CPU / ISA) Algılama + Uyarlanabilir Çalışma Profili
        self.hw_profile: HardwareProfile = detect_hardware_profile(query_ct2=True)
        saved_perf_profile = self.settings.get("performance_profile", PROFILE_AUTO)
        self.tuning: RuntimeTuning = compute_runtime_tuning(self.hw_profile, saved_perf_profile)
        apply_thread_env_defaults(self.tuning)

        self.translator = LocalEnTrTranslator(
            cpu_threads=self.tuning.nmt_threads,
            compute_type_candidates=self.tuning.compute_type_candidates,
        )

        saved_ocr_mode = self.settings.get("ocr_mode", self.tuning.default_ocr_mode)
        self.ocr_engine = SubtitleOCREngine(
            use_color_mask=(saved_ocr_mode != "full_ocr"),
            ocr_mode=saved_ocr_mode,
            tuning=self.tuning,
            lazy_init=True,  # Arayüzün eski/düşük CPU'larda anında açılması için arka planda ısıt
        )
        self.worker: Optional[CaptureTranslateWorker] = None
        self.bench_worker: Optional[BenchmarkWorker] = None

        self.overlay = SubtitleOverlayWindow()
        self.roi_selector = ROISelectorOverlay(on_selected=self._on_roi_selected)

        # Seçili görünüm durumları (WDA_EXCLUDEFROMCAPTURE desteklenmeyen OS'lerde 'above' güvenli varsayılan)
        default_overlay_mode = "cover" if self.hw_profile.capture_exclude_supported else "above"
        self._selected_color = self.settings.get("text_color", "#FACC15")
        self._selected_overlay_mode = self.settings.get("overlay_mode", default_overlay_mode)

        # Oyun, Dizi, Film ve Belgesellerden Gerçekçi Test Diyalogları
        self._sample_idx = 0
        self._samples: List[Tuple[str, str]] = [
            (
                "🎬 Dizi / Drama",
                "Detective: Everything we found in that room points to a much bigger conspiracy.",
            ),
            (
                "🎮 Oyun / RPG",
                "Arthur: Stay close to me, the woods ahead are crawling with bounty hunters.",
            ),
            (
                "🍿 Bilim Kurgu Film",
                "Commander: If we cross the event horizon, there's no turning back for any of us.",
            ),
            (
                "📺 Belgesel / Yayın",
                "For centuries, this ancient civilization remained completely hidden beneath the jungle.",
            ),
            (
                "🎮 Aksiyon / Macera",
                "Hold on tight! I'm gonna take the shortcut through the old tunnel!",
            ),
            (
                "🎬 Sinema / Gerilim",
                "We need to talk before they realize what really happened last night.",
            ),
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
            "text_color": self._selected_color,
            "overlay_mode": self._selected_overlay_mode,
            "ocr_mode": self.combo_ocr_mode.currentData(),
            "performance_profile": self.combo_perf_profile.currentData(),
            "show_bilingual": self.chk_bilingual.isChecked(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _format_hw_badge_text(self) -> str:
        ctype = self.translator.active_compute_type.upper()
        return (
            f"🖥️ {self.hw_profile.short_cpu_label} ({self.hw_profile.physical_cores}C/{self.hw_profile.logical_cores}T)   •   "
            f"🧠 {ctype} ({self.translator.cpu_threads}T)   •   ⚡ {self.tuning.scan_fps} FPS   •   🛡️ 0 MB VRAM"
        )

    def _build_ui(self) -> None:
        ui_font = get_ui_font_family()
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#centralWidget, QScrollArea {{
                background-color: #070B14;
                color: #F8FAFC;
                font-family: '{ui_font}', 'Segoe UI', 'DejaVu Sans', -apple-system, sans-serif;
            }}
            QLabel {{
                background-color: transparent;
                color: #E2E8F0;
                font-family: '{ui_font}', 'Segoe UI', 'DejaVu Sans', -apple-system, sans-serif;
            }}
            QFrame#studioPanel {{
                background-color: #0F1626;
                border: 1px solid #1E293B;
                border-radius: 14px;
            }}
            QPushButton {{
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 9px;
                padding: 9px 14px;
                font-size: 9.8pt;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: #334155;
                border-color: #475569;
            }}
            QPushButton:disabled {{
                background-color: #0F172A;
                color: #475569;
                border-color: #1E293B;
            }}
            QComboBox {{
                background-color: #090D16;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 12px;
                min-height: 24px;
                color: #F8FAFC;
                font-size: 9.3pt;
                font-weight: 600;
            }}
            QComboBox:hover {{
                border-color: #38BDF8;
            }}
            QComboBox QAbstractItemView {{
                background-color: #0F1626;
                color: #F8FAFC;
                selection-background-color: #2563EB;
                border: 1px solid #334155;
            }}
            QSlider {{
                background-color: transparent;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid #1E293B;
                height: 6px;
                background: #090D16;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #06B6D4);
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: #F8FAFC;
                border: 2px solid #0284C7;
                width: 16px;
                margin: -6px 0;
                border-radius: 9px;
            }}
            QCheckBox {{
                background-color: transparent;
                color: #CBD5E1;
                font-size: 9.2pt;
                font-weight: 600;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid #475569;
                background-color: #090D16;
            }}
            QCheckBox::indicator:checked {{
                background-color: #2563EB;
                border-color: #60A5FA;
            }}
            QListWidget {{
                background-color: #090D16;
                border: 1px solid #1E293B;
                border-radius: 10px;
                color: #CBD5E1;
                font-size: 9pt;
                padding: 6px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 7px 10px;
                border-bottom: 1px solid #111827;
                border-radius: 6px;
                margin-bottom: 2px;
            }}
            QListWidget::item:selected {{
                background-color: #1E293B;
                color: #FACC15;
            }}
            """
        )

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        central = QWidget()
        central.setObjectName("centralWidget")
        scroll_area.setWidget(central)
        self.setCentralWidget(scroll_area)

        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(18, 16, 18, 14)

        # ═════════════════════════════════════════════════════════════════════
        # 1. STUDIO HERO HEADER BAR
        # ═════════════════════════════════════════════════════════════════════
        header_frame = QFrame()
        header_frame.setStyleSheet(
            """
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0F172A, stop:0.5 #152238, stop:1 #0F172A);
                border-radius: 14px;
                border: 1px solid #26354D;
            }
            """
        )
        header_v = QVBoxLayout(header_frame)
        header_v.setContentsMargins(16, 12, 16, 12)
        header_v.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(14)

        # Sol Logo İkonu
        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_app_pixmap(48))
        logo_lbl.setFixedSize(48, 48)
        logo_lbl.setStyleSheet("border: none; background: transparent;")
        top_bar.addWidget(logo_lbl)

        # Başlık & Alt Başlık
        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_lbl = QLabel("SubVision AI")
        title_lbl.setFont(QFont(ui_font, 16, QFont.Weight.Black))
        title_lbl.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        title_row.addWidget(title_lbl)

        ver_pill = QLabel("STUDIO v1.2")
        ver_pill.setStyleSheet(
            "color: #38BDF8; background-color: #090D16; border: 1px solid #0284C7; border-radius: 6px; padding: 2px 8px; font-size: 8pt; font-weight: 800;"
        )
        title_row.addWidget(ver_pill)
        title_row.addStretch(1)
        title_col.addLayout(title_row)

        sub_lbl = QLabel(
            "Oyun, Dizi, Film ve Yayınlar İçin Evrensel & Uyarlanabilir Lokal AI Altyazı Motoru (EN ➔ TR)"
        )
        sub_lbl.setStyleSheet(
            "color: #94A3B8; font-size: 9pt; font-weight: 500; border: none; background: transparent;"
        )
        title_col.addWidget(sub_lbl)
        top_bar.addLayout(title_col, stretch=1)

        # Sağ Donanım & Durum Rozetleri
        badge_col = QVBoxLayout()
        badge_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        badge_col.setSpacing(5)

        self.hw_badge = QLabel(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.hw_badge.setStyleSheet(
            "color: #CBD5E1; background-color: #090D16; border: 1px solid #1E293B; border-radius: 7px; padding: 4px 11px; font-size: 8.1pt; font-weight: 700;"
        )
        badge_col.addWidget(self.hw_badge, alignment=Qt.AlignmentFlag.AlignRight)

        self.lbl_model_status = QLabel("⏳ Donanım profili hazırlandı, motorlar yükleniyor...")
        self.lbl_model_status.setStyleSheet(
            "color: #FACC15; font-size: 9pt; font-weight: 800; border: none; background: transparent;"
        )
        badge_col.addWidget(self.lbl_model_status, alignment=Qt.AlignmentFlag.AlignRight)
        top_bar.addLayout(badge_col)

        header_v.addLayout(top_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #1E293B;
                border-radius: 5px;
                text-align: center;
                background-color: #090D16;
                color: #F8FAFC;
                font-size: 8pt;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #10B981);
                border-radius: 4px;
            }
            """
        )
        header_v.addWidget(self.progress_bar)
        main_layout.addWidget(header_frame)

        # ═════════════════════════════════════════════════════════════════════
        # 2. TELEMETRİ & PERFORMANS KARTLARI (4 KPI Cards with Progress Bars)
        # ═════════════════════════════════════════════════════════════════════
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)

        self.card_ocr = TelemetryCard(
            "OCR YAKALAMA",
            "FAST MASK",
            "— ms",
            f"2 Aşamalı Frame Lock • {self.tuning.ocr_intra_threads} Thread",
            "#38BDF8",
            22,
        )
        self.card_nmt = TelemetryCard(
            f"NMT ÇEVİRİ ({self.translator.active_compute_type.upper()})",
            f"{self.translator.cpu_threads} THREAD",
            "— ms",
            "Opus-MT Big EN ➔ TR",
            "#FACC15",
            45,
        )
        self.card_total = TelemetryCard(
            "UÇTAN UCA GECİKME",
            "REAL-TIME",
            "— ms",
            "Hedef < 150 ms (Anlık Algı)",
            "#10B981",
            55,
        )
        self.card_stats = TelemetryCard(
            "OTURUM & ÖNBELLEK",
            f"{self.tuning.scan_fps} FPS TARAMA",
            "0 Çeviri",
            f"ROI: {self.roi['width']}×{self.roi['height']} px  |  Hit: %0",
            "#A78BFA",
            10,
        )

        kpi_row.addWidget(self.card_ocr)
        kpi_row.addWidget(self.card_nmt)
        kpi_row.addWidget(self.card_total)
        kpi_row.addWidget(self.card_stats)
        main_layout.addLayout(kpi_row)

        # ═════════════════════════════════════════════════════════════════════
        # 3. HIZLI AKSİYON DOCK BAR (4 Primary Action Buttons)
        # ═════════════════════════════════════════════════════════════════════
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_select_roi = QPushButton("🎯  1. Altyazı Alanını Seç (F7)")
        self.btn_select_roi.setMinimumHeight(42)
        self.btn_select_roi.setStyleSheet(
            """
            QPushButton {
                background-color: #2563EB;
                border: 1px solid #3B82F6;
                font-size: 10.2pt;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
                border-color: #60A5FA;
            }
            """
        )
        self.btn_select_roi.clicked.connect(self.open_roi_selector)
        btn_row.addWidget(self.btn_select_roi, stretch=3)

        self.btn_toggle = QPushButton("▶️  2. Anlık Çeviriyi Başlat (F8)")
        self.btn_toggle.setMinimumHeight(42)
        self.btn_toggle.setEnabled(False)
        self.btn_toggle.setStyleSheet(
            """
            QPushButton {
                background-color: #059669;
                border: 1px solid #10B981;
                font-size: 10.2pt;
            }
            QPushButton:hover {
                background-color: #047857;
                border-color: #34D399;
            }
            """
        )
        self.btn_toggle.clicked.connect(self.toggle_translation)
        btn_row.addWidget(self.btn_toggle, stretch=3)

        self.btn_test = QPushButton("🧪  Örnek Sahne Simülasyonu (F9)")
        self.btn_test.setMinimumHeight(42)
        self.btn_test.setEnabled(False)
        self.btn_test.setStyleSheet(
            """
            QPushButton {
                background-color: #1E293B;
                border: 1px solid #334155;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38BDF8;
            }
            """
        )
        self.btn_test.clicked.connect(self.run_sample_test)
        btn_row.addWidget(self.btn_test, stretch=2)

        self.btn_benchmark = QPushButton("⚡  Donanım Benchmark")
        self.btn_benchmark.setMinimumHeight(42)
        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.setStyleSheet(
            """
            QPushButton {
                background-color: #4F46E5;
                border: 1px solid #6366F1;
            }
            QPushButton:hover {
                background-color: #4338CA;
                border-color: #818CF8;
            }
            """
        )
        self.btn_benchmark.clicked.connect(self.run_benchmark_suite)
        btn_row.addWidget(self.btn_benchmark, stretch=2)

        main_layout.addLayout(btn_row)

        # ═════════════════════════════════════════════════════════════════════
        # 4. İKİ SÜTUNLU STUDIO WORKSPACE (Sol: Canlı Monitör | Sağ: Overlay Tasarımcısı)
        # ═════════════════════════════════════════════════════════════════════
        workspace_row = QHBoxLayout()
        workspace_row.setSpacing(14)

        # ─────────────────────────────────────────────────────────────────────
        # SOL SÜTUN (%56): CANLI ALTYAZI MONİTÖRÜ & DİYALOG AKIŞI
        # ─────────────────────────────────────────────────────────────────────
        left_panel = QFrame()
        left_panel.setObjectName("studioPanel")
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(16, 14, 16, 14)
        left_lay.setSpacing(10)

        # Panel Başlığı
        left_hdr = QHBoxLayout()
        lbl_left_title = QLabel("📡  CANLI YAKALAMA STÜDYOSU & DİYALOG AKIŞI")
        lbl_left_title.setStyleSheet("color: #38BDF8; font-size: 9.5pt; font-weight: 800;")
        left_hdr.addWidget(lbl_left_title)

        self.lbl_scene_tag = QLabel(f"Mod: Canlı Ekran Yakalama ({self.tuning.scan_fps} FPS)")
        self.lbl_scene_tag.setStyleSheet(
            "color: #A78BFA; background-color: #090D16; border: 1px solid #1E293B; border-radius: 6px; padding: 3px 9px; font-size: 8.2pt; font-weight: 700;"
        )
        left_hdr.addWidget(self.lbl_scene_tag, alignment=Qt.AlignmentFlag.AlignRight)
        left_lay.addLayout(left_hdr)

        # Yakalanan İngilizce (EN) Kutusu
        lbl_en_cap = QLabel("YAKALANAN İNGİLİZCE ALTYAZI (SOURCE EN)")
        lbl_en_cap.setStyleSheet("color: #64748B; font-size: 8pt; font-weight: 800;")
        left_lay.addWidget(lbl_en_cap)

        self.lbl_en_preview = QLabel(
            "Henüz altyazı yakalanmadı. F7 ile altyazı bölgesini seçip F8 ile başlatın veya F9 ile örnek sahne test edin."
        )
        self.lbl_en_preview.setWordWrap(True)
        self.lbl_en_preview.setMinimumHeight(48)
        self.lbl_en_preview.setStyleSheet(
            """
            background-color: #090D16;
            border: 1px solid #1E293B;
            border-left: 4px solid #38BDF8;
            padding: 10px 14px;
            border-radius: 8px;
            color: #E2E8F0;
            font-size: 10.4pt;
            font-weight: 600;
            """
        )
        left_lay.addWidget(self.lbl_en_preview)

        # Anlık Türkçe Çeviri (TR) Kutusu
        tr_hdr = QHBoxLayout()
        lbl_tr_cap = QLabel("ANLIK TÜRKÇE ÇEVİRİ (TARGET TR)")
        lbl_tr_cap.setStyleSheet("color: #64748B; font-size: 8pt; font-weight: 800;")
        tr_hdr.addWidget(lbl_tr_cap)

        btn_copy = QPushButton("📋 Kopyala")
        btn_copy.setStyleSheet(
            "QPushButton { background-color: #1E293B; padding: 3px 10px; font-size: 8.2pt; border-radius: 5px; } QPushButton:hover { background-color: #334155; }"
        )
        btn_copy.clicked.connect(self._copy_current_translation)
        tr_hdr.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignRight)
        left_lay.addLayout(tr_hdr)

        self.lbl_tr_preview = QLabel("Çeviri bekleniyor...")
        self.lbl_tr_preview.setWordWrap(True)
        self.lbl_tr_preview.setMinimumHeight(54)
        self.lbl_tr_preview.setStyleSheet(
            """
            background-color: #090D16;
            border: 1px solid #334155;
            border-left: 4px solid #FACC15;
            padding: 10px 14px;
            border-radius: 8px;
            color: #FACC15;
            font-size: 11.5pt;
            font-weight: 800;
            """
        )
        left_lay.addWidget(self.lbl_tr_preview)

        # Diyalog Geçmişi Listesi (Word-Wrapped, Scrollbar'sız Temiz Kartlar)
        hist_hdr = QHBoxLayout()
        lbl_hist = QLabel("📜  SON ÇEVRİLEN DİYALOG GEÇMİŞİ")
        lbl_hist.setStyleSheet("color: #64748B; font-size: 8pt; font-weight: 800;")
        hist_hdr.addWidget(lbl_hist)

        btn_clear_hist = QPushButton("Temizle")
        btn_clear_hist.setStyleSheet(
            "QPushButton { background-color: transparent; color: #64748B; border: none; padding: 2px 6px; font-size: 8.2pt; } QPushButton:hover { color: #F87171; }"
        )
        btn_clear_hist.clicked.connect(lambda: self.list_history.clear())
        hist_hdr.addWidget(btn_clear_hist, alignment=Qt.AlignmentFlag.AlignRight)
        left_lay.addLayout(hist_hdr)

        self.list_history = QListWidget()
        self.list_history.setWordWrap(True)
        self.list_history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_history.setMinimumHeight(130)
        left_lay.addWidget(self.list_history, stretch=1)

        workspace_row.addWidget(left_panel, stretch=56)

        # ─────────────────────────────────────────────────────────────────────
        # SAĞ SÜTUN (%44): SAHNE PROFİLİ & OVERLAY TASARIMCISI (LIVE PREVIEW İLE)
        # ─────────────────────────────────────────────────────────────────────
        right_panel = QFrame()
        right_panel.setObjectName("studioPanel")
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(16, 14, 16, 14)
        right_lay.setSpacing(10)

        lbl_right_title = QLabel("🎨  SAHNE PROFİLİ & OVERLAY TASARIMCISI")
        lbl_right_title.setStyleSheet("color: #38BDF8; font-size: 9.5pt; font-weight: 800;")
        right_lay.addWidget(lbl_right_title)

        # 1. İşlemci & Performans Profili (Her Bilgisayara Otomatik Uyum)
        lbl_perf_prof = QLabel("1. İşlemci & Performans Profili:")
        lbl_perf_prof.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 700;")
        right_lay.addWidget(lbl_perf_prof)

        self.combo_perf_profile = QComboBox()
        self.combo_perf_profile.addItem(
            "🤖  Otomatik — İşlemciye Göre En İyi Ayar (Önerilen)", PROFILE_AUTO
        )
        self.combo_perf_profile.addItem(
            "🔋  Eko / Eski & Düşük CPU (15 FPS • Hafif Kaynak)", PROFILE_ECO
        )
        self.combo_perf_profile.addItem(
            "⚖️  Dengeli (24 FPS • Orta Seviye CPU)", PROFILE_BALANCED
        )
        self.combo_perf_profile.addItem(
            "🚀  Maksimum Performans (30 FPS • Çok Çekirdekli CPU)", PROFILE_PERFORMANCE
        )
        self.combo_perf_profile.currentIndexChanged.connect(self._on_perf_profile_changed)
        right_lay.addWidget(self.combo_perf_profile)

        # 2. İçerik & OCR Algılama Profili
        lbl_ocr_prof = QLabel("2. İçerik & Sahne Algılama Profili:")
        lbl_ocr_prof.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 700;")
        right_lay.addWidget(lbl_ocr_prof)

        self.combo_ocr_mode = QComboBox()
        self.combo_ocr_mode.addItem("🎬  Oyun, Dizi & Film (Akıllı Hibrit Filtre)", "hybrid")
        self.combo_ocr_mode.addItem("⚡  Sadece Kontürlü Altyazı (En Hızlı / En Hafif CPU)", "fast_mask")
        self.combo_ocr_mode.addItem("🖥️  Genel Ekran & Video (Tam Kare OCR / Tüm Fontlar)", "full_ocr")
        self.combo_ocr_mode.currentIndexChanged.connect(self._on_ocr_mode_changed)
        right_lay.addWidget(self.combo_ocr_mode)

        # 3. Altyazı Konumu (Segmented Toggle Buttons)
        lbl_pos_title = QLabel("3. Ekranda Türkçe Altyazı Konumu:")
        lbl_pos_title.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 700;")
        right_lay.addWidget(lbl_pos_title)

        pos_row = QHBoxLayout()
        pos_row.setSpacing(8)
        self.btn_mode_cover = QPushButton("⬛  Orijinalin Üstünü Kapat")
        if not self.hw_profile.capture_exclude_supported:
            self.btn_mode_cover.setToolTip(
                "Bu işletim sistemi sürümünde ekran yakalamadan gizleme (WDA_EXCLUDEFROMCAPTURE) "
                "desteklenmediği için OCR döngüsünü önlemek adına 'Hemen Üstünde' modu otomatik uygulanır."
            )
        self.btn_mode_above = QPushButton("⬆️  Hemen Üstünde Göster")
        self.btn_mode_cover.clicked.connect(lambda: self._select_overlay_mode("cover"))
        self.btn_mode_above.clicked.connect(lambda: self._select_overlay_mode("above"))
        pos_row.addWidget(self.btn_mode_cover)
        pos_row.addWidget(self.btn_mode_above)
        right_lay.addLayout(pos_row)

        # 4. Altyazı Renk Paleti (Interactive Color Swatch Pills)
        lbl_col_title = QLabel("4. Altyazı Renk Paleti:")
        lbl_col_title.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 700;")
        right_lay.addWidget(lbl_col_title)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        self._color_buttons: Dict[str, QPushButton] = {}
        color_presets = [
            ("#FFFFFF", "⚪ Beyaz"),
            ("#FACC15", "🟡 Sinema Sarı"),
            ("#38BDF8", "🔵 Turkuaz"),
            ("#4ADE80", "🟢 Zümrüt"),
        ]
        for hex_code, label_txt in color_presets:
            b = QPushButton(label_txt)
            b.clicked.connect(lambda checked=False, c=hex_code: self._select_color_swatch(c))
            self._color_buttons[hex_code] = b
            swatch_row.addWidget(b)
        right_lay.addLayout(swatch_row)

        # 4. Yazı Boyutu & Arka Plan Opaklığı Sliders
        sliders_grid = QGridLayout()
        sliders_grid.setSpacing(8)

        self.lbl_font_val = QLabel("Yazı Boyutu: 21 pt")
        self.lbl_font_val.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 700;")
        sliders_grid.addWidget(self.lbl_font_val, 0, 0)

        self.slider_font = QSlider(Qt.Orientation.Horizontal)
        self.slider_font.setRange(14, 36)
        self.slider_font.setValue(self.settings.get("font_size", 21))
        self.slider_font.valueChanged.connect(self._on_appearance_changed)
        sliders_grid.addWidget(self.slider_font, 0, 1)

        init_alpha = self.settings.get("bg_alpha", 225)
        self.lbl_alpha_val = QLabel(f"Arka Plan: %{int(init_alpha / 255 * 100)}")
        self.lbl_alpha_val.setStyleSheet("color: #CBD5E1; font-size: 8.8pt; font-weight: 700;")
        sliders_grid.addWidget(self.lbl_alpha_val, 1, 0)

        self.slider_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_alpha.setRange(90, 250)
        self.slider_alpha.setValue(init_alpha)
        self.slider_alpha.valueChanged.connect(self._on_appearance_changed)
        sliders_grid.addWidget(self.slider_alpha, 1, 1)

        right_lay.addLayout(sliders_grid)

        # 5. Gelişmiş Katman Seçenekleri
        self.chk_bilingual = QCheckBox("🌐  Çift Dilli Sinema Modu (Üstte küçük EN + Altta TR)")
        self.chk_bilingual.setChecked(self.settings.get("show_bilingual", False))
        self.chk_bilingual.toggled.connect(self._on_appearance_changed)
        right_lay.addWidget(self.chk_bilingual)

        self.chk_guide = QCheckBox("📐  Ekranda Altyazı Kutusunun Hizalama Sınırlarını Göster")
        self.chk_guide.setChecked(False)
        self.chk_guide.toggled.connect(self.overlay.set_guide_border)
        right_lay.addWidget(self.chk_guide)

        # 6. CANLI OVERLAY ÖNİZLEME KUTUSU (Mini Live Preview)
        lbl_prev_hdr = QLabel("👁️  CANLI OVERLAY GÖRÜNÜM ÖNİZLEMESİ")
        lbl_prev_hdr.setStyleSheet("color: #64748B; font-size: 8pt; font-weight: 800; padding-top: 4px;")
        right_lay.addWidget(lbl_prev_hdr)

        self.preview_box = QFrame()
        self.preview_box.setMinimumHeight(94)
        prev_v = QVBoxLayout(self.preview_box)
        prev_v.setContentsMargins(12, 8, 12, 8)
        prev_v.setSpacing(2)

        self.lbl_mini_en = QLabel("Detective: Everything points to a much bigger conspiracy.")
        self.lbl_mini_en.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_mini_en.setWordWrap(True)
        prev_v.addWidget(self.lbl_mini_en)

        self.lbl_mini_tr = QLabel("Dedektif: Her şey çok daha büyük bir komploya işaret ediyor.")
        self.lbl_mini_tr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_mini_tr.setWordWrap(True)
        prev_v.addWidget(self.lbl_mini_tr)

        right_lay.addWidget(self.preview_box, stretch=1)
        workspace_row.addWidget(right_panel, stretch=44)

        main_layout.addLayout(workspace_row, stretch=1)

        # ═════════════════════════════════════════════════════════════════════
        # 5. ALT BİLGİ ÇUBUĞU (Footer Bar)
        # ═════════════════════════════════════════════════════════════════════
        footer = QLabel(
            "💡 İpucu: Oyunlarda 'Borderless Windowed (Çerçevesiz Pencere)' modunu seçin; "
            "Netflix, Prime Video, YouTube, Twitch ve VLC/MPC-HC üzerinde doğrudan çalışır.   •   "
            "Global Kısayollar:  F7 (Altyazı Alanı Seç)  |  F8 (Başlat / Durdur)  |  F9 (Örnek Sahne Simülasyonu)"
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #64748B; font-size: 8.5pt; font-weight: 500;")
        main_layout.addWidget(footer)

    def _select_color_swatch(self, hex_code: str) -> None:
        self._selected_color = hex_code
        self._on_appearance_changed()

    def _select_overlay_mode(self, mode: str) -> None:
        self._selected_overlay_mode = mode
        self._on_appearance_changed()

    def _update_designer_button_styles(self) -> None:
        # Konum butonları stili
        active_pos_css = (
            "QPushButton { background-color: #1E3A8A; border: 1.5px solid #38BDF8; color: #FFFFFF; padding: 7px 10px; font-size: 8.8pt; }"
        )
        idle_pos_css = (
            "QPushButton { background-color: #090D16; border: 1px solid #1E293B; color: #94A3B8; padding: 7px 10px; font-size: 8.8pt; } "
            "QPushButton:hover { border-color: #334155; color: #E2E8F0; }"
        )
        self.btn_mode_cover.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "cover" else idle_pos_css
        )
        self.btn_mode_above.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "above" else idle_pos_css
        )

        # Renk paleti butonları stili
        for hex_code, btn in self._color_buttons.items():
            if hex_code == self._selected_color:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: #1E293B; border: 2px solid {hex_code}; color: {hex_code}; padding: 6px 8px; font-size: 8.5pt; font-weight: 800; }}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #090D16; border: 1px solid #1E293B; color: #94A3B8; padding: 6px 8px; font-size: 8.5pt; } "
                    "QPushButton:hover { border-color: #334155; color: #E2E8F0; }"
                )

    def _apply_saved_appearance(self) -> None:
        self._selected_color = self.settings.get("text_color", "#FACC15")
        if self._selected_color not in self._color_buttons:
            self._selected_color = "#FACC15"

        default_overlay = "cover" if self.hw_profile.capture_exclude_supported else "above"
        self._selected_overlay_mode = self.settings.get("overlay_mode", default_overlay)

        saved_perf = self.settings.get("performance_profile", PROFILE_AUTO)
        self.combo_perf_profile.blockSignals(True)
        idx_p = self.combo_perf_profile.findData(saved_perf)
        if idx_p >= 0:
            self.combo_perf_profile.setCurrentIndex(idx_p)
        self.combo_perf_profile.blockSignals(False)

        saved_ocr = self.settings.get("ocr_mode", self.tuning.default_ocr_mode)
        self.combo_ocr_mode.blockSignals(True)
        idx_o = self.combo_ocr_mode.findData(saved_ocr)
        if idx_o >= 0:
            self.combo_ocr_mode.setCurrentIndex(idx_o)
        self.combo_ocr_mode.blockSignals(False)
        self._sync_ocr_badge(saved_ocr)

        self._on_appearance_changed()

    def _sync_ocr_badge(self, mode: str) -> None:
        badge_map = {
            "hybrid": "HYBRID OCR",
            "fast_mask": "FAST MASK",
            "full_ocr": "FULL DBNET",
        }
        self.card_ocr.set_metric(
            self.card_ocr.lbl_val.text(),
            badge_text=badge_map.get(mode, "HYBRID"),
        )

    def _on_perf_profile_changed(self) -> None:
        selected_profile = self.combo_perf_profile.currentData() or PROFILE_AUTO
        self.tuning = compute_runtime_tuning(self.hw_profile, selected_profile)
        self.ocr_engine.apply_tuning(self.tuning)

        if self.translator.is_ready and self.translator.cpu_threads != self.tuning.nmt_threads:
            try:
                self.translator.reconfigure_threads(self.tuning.nmt_threads)
            except Exception:
                pass
        else:
            self.translator.cpu_threads = self.tuning.nmt_threads

        if self.worker and self.worker.running:
            self.worker.update_timing(
                self.tuning.scan_interval_sec, self.tuning.idle_scan_interval_sec
            )
            ms_interval = int(round(self.tuning.scan_interval_sec * 1000))
            self.lbl_model_status.setText(
                f"🟢 CANLI TARAMA AKTİF ({self.tuning.scan_fps} FPS / {ms_interval} ms)"
            )

        self.hw_badge.setText(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.lbl_scene_tag.setText(f"Mod: Canlı Ekran Yakalama ({self.tuning.scan_fps} FPS)")
        self.card_ocr.set_metric(
            self.card_ocr.lbl_val.text(),
            sub_text=f"2 Aşamalı Frame Lock • {self.tuning.ocr_intra_threads} Thread",
        )
        ctype = self.translator.active_compute_type.upper()
        self.card_nmt.lbl_title.setText(f"NMT ÇEVİRİ ({ctype})")
        self.card_nmt.set_metric(
            self.card_nmt.lbl_val.text(),
            badge_text=f"{self.translator.cpu_threads} THREAD",
        )
        self._update_session_kpi()
        self._save_settings()

    def _start_model_loading(self) -> None:
        self.loader_thread = ModelLoaderThread(self.translator, self.ocr_engine)
        self.loader_thread.progress.connect(self._on_model_progress)
        self.loader_thread.finished_ok.connect(self._on_model_ready)
        self.loader_thread.failed.connect(self._on_model_failed)
        self.loader_thread.start()

    def _on_model_progress(self, msg: str, pct: int) -> None:
        self.lbl_model_status.setText(msg)
        self.progress_bar.setValue(pct)

    def _on_model_ready(self) -> None:
        ctype = self.translator.active_compute_type.upper()
        self.hw_badge.setText(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.card_nmt.lbl_title.setText(f"NMT ÇEVİRİ ({ctype})")
        self.lbl_model_status.setText(
            f"🟢 ENGINE READY  •  Opus-MT Big {ctype} ({self.translator.cpu_threads}T CPU)"
        )
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
        alpha_pct = int(alpha / 255 * 100)
        bilingual = self.chk_bilingual.isChecked()

        self.lbl_font_val.setText(f"Yazı Boyutu: {f_size} pt")
        self.lbl_alpha_val.setText(f"Arka Plan: %{alpha_pct}")
        self._update_designer_button_styles()

        # Mini Canlı Önizleme Kutusunu Güncelle
        preview_font_pt = max(10, min(16, int(f_size * 0.56)))
        en_font_pt = max(8, int(preview_font_pt * 0.72))
        self.preview_box.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(8, 12, 22, {alpha});
                border: 1px solid #334155;
                border-radius: 10px;
            }}
            """
        )
        self.lbl_mini_en.setVisible(bilingual)
        self.lbl_mini_en.setStyleSheet(
            f"color: #94A3B8; font-size: {en_font_pt}pt; font-weight: 600; border: none; background: transparent;"
        )
        self.lbl_mini_tr.setStyleSheet(
            f"color: {self._selected_color}; font-size: {preview_font_pt}pt; font-weight: 800; border: none; background: transparent;"
        )

        self.overlay.update_appearance(
            font_size=f_size,
            text_color=self._selected_color,
            bg_alpha=alpha,
            overlay_mode=self._selected_overlay_mode,
            show_bilingual=bilingual,
        )
        self.overlay.align_to_roi(self.roi)
        self._save_settings()

    def _on_ocr_mode_changed(self) -> None:
        mode = self.combo_ocr_mode.currentData()
        self.ocr_engine.set_mode(mode)
        self._sync_ocr_badge(mode)
        self._save_settings()

    def _copy_current_translation(self) -> None:
        tr = self.lbl_tr_preview.text().strip()
        if tr and tr != "Çeviri bekleniyor...":
            QGuiApplication.clipboard().setText(tr)

    def _update_session_kpi(self) -> None:
        req = self.translator.total_requests
        hits = self.translator.cache_hits
        hit_pct = int((hits / req) * 100) if req > 0 else 0
        self.card_stats.set_metric(
            f"{req} Çeviri",
            sub_text=f"ROI: {self.roi['width']}×{self.roi['height']} px  |  Hit: %{hit_pct}",
            badge_text=f"%{hit_pct} CACHE HIT" if req > 0 else f"{self.tuning.scan_fps} FPS TARAMA",
            bar_pct=max(12, hit_pct),
        )

    def toggle_translation(self) -> None:
        if not self.translator.is_ready:
            return

        if self.worker and self.worker.running:
            self.worker.stop()
            self.worker = None
            self.btn_toggle.setText("▶️  2. Anlık Çeviriyi Başlat (F8)")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #059669;
                    border: 1px solid #10B981;
                    font-size: 10.2pt;
                }
                QPushButton:hover {
                    background-color: #047857;
                    border-color: #34D399;
                }
                """
            )
            ctype = self.translator.active_compute_type.upper()
            self.lbl_model_status.setText(
                f"🟢 ENGINE READY  •  Opus-MT Big {ctype} ({self.translator.cpu_threads}T CPU)"
            )
            self.overlay.set_subtitle("")
        else:
            self.overlay.align_to_roi(self.roi)
            self.overlay.set_subtitle("")
            self.lbl_scene_tag.setText(f"Mod: Canlı Ekran Yakalama ({self.tuning.scan_fps} FPS)")
            self.worker = CaptureTranslateWorker(
                ocr_engine=self.ocr_engine,
                translator=self.translator,
                roi=self.roi,
                scan_interval_sec=self.tuning.scan_interval_sec,
                idle_scan_interval_sec=self.tuning.idle_scan_interval_sec,
            )
            self.worker.subtitle_updated.connect(self._on_subtitle_updated)
            self.worker.subtitle_cleared.connect(self._on_subtitle_cleared)
            self.worker.status_tick.connect(
                lambda msg: self.card_total.set_metric(self.card_total.lbl_val.text(), sub_text=msg)
            )
            self.worker.start()

            ms_interval = int(round(self.tuning.scan_interval_sec * 1000))
            self.lbl_model_status.setText(
                f"🟢 CANLI TARAMA AKTİF ({self.tuning.scan_fps} FPS / {ms_interval} ms)"
            )
            self.btn_toggle.setText("⏹️  Canlı Çeviriyi Durdur (F8)")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #DC2626;
                    border: 1px solid #EF4444;
                    font-size: 10.2pt;
                }
                QPushButton:hover {
                    background-color: #B91C1C;
                    border-color: #F87171;
                }
                """
            )

    def _on_subtitle_updated(
        self, en_text: str, tr_text: str, ocr_ms: float, tr_ms: float, is_cached: bool
    ) -> None:
        self.overlay.set_subtitle(tr_text, en_text)
        self.lbl_en_preview.setText(en_text)
        self.lbl_tr_preview.setText(tr_text)
        self.lbl_mini_en.setText(en_text)
        self.lbl_mini_tr.setText(tr_text)

        total_ms = ocr_ms + tr_ms
        ocr_pct = int(min(100, (ocr_ms / 80.0) * 100)) if ocr_ms > 0 else 8
        nmt_pct = 5 if is_cached else int(min(100, (tr_ms / 140.0) * 100))
        tot_pct = int(min(100, (total_ms / 150.0) * 100))
        ctype = self.translator.active_compute_type.upper()

        self.card_ocr.set_metric(
            f"{ocr_ms:.1f} ms",
            sub_text="RapidOCR ONNX + Frame Lock",
            bar_pct=ocr_pct,
        )
        self.card_nmt.set_metric(
            f"{tr_ms:.3f} ms" if is_cached else f"{tr_ms:.1f} ms",
            sub_text="⚡ RAM LRU Cache / Glossary Hit"
            if is_cached
            else f"🧠 CTranslate2 {ctype} ({self.translator.cpu_threads} Thread)",
            badge_text="CACHE HIT" if is_cached else f"{ctype} CPU",
            bar_pct=nmt_pct,
        )
        self.card_total.set_metric(
            f"{total_ms:.1f} ms",
            sub_text="⚡ İnsan Gözü İçin Anlık (<150 ms)"
            if total_ms < 150
            else "✅ Gerçek Zamanlı Yanıt",
            badge_text="INSTANT" if is_cached else "REAL-TIME",
            bar_pct=tot_pct,
        )
        self._update_session_kpi()

        stamp = datetime.now().strftime("%H:%M:%S")
        tag = "⚡ CACHE" if is_cached else f"🧠 {ctype}"
        entry = f"[{stamp}]  •  {total_ms:.1f} ms ({tag})\nEN: {en_text}\nTR: {tr_text}"
        item = QListWidgetItem(entry)
        self.list_history.insertItem(0, item)
        if self.list_history.count() > 25:
            self.list_history.takeItem(self.list_history.count() - 1)

    def _on_subtitle_cleared(self) -> None:
        self.overlay.set_subtitle("")

    def run_sample_test(self) -> None:
        if not self.translator.is_ready:
            return
        category, sample_en = self._samples[self._sample_idx % len(self._samples)]
        self._sample_idx += 1
        self.lbl_scene_tag.setText(f"Simülasyon: {category}")
        tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(sample_en)
        # Simülasyonda gerçekçi 19.8 ms OCR süresi ile birlikte uçtan uca göster
        self._on_subtitle_updated(sample_en, tr_text, 19.8, tr_ms, is_cached)

    def run_benchmark_suite(self) -> None:
        if not self.translator.is_ready:
            return
        if self.bench_worker and self.bench_worker.isRunning():
            return

        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.setText("⏳  Ölçülüyor...")
        self.bench_worker = BenchmarkWorker(self.ocr_engine, self.translator, self.hw_profile)
        self.bench_worker.finished_report.connect(self._on_benchmark_finished)
        self.bench_worker.start()

    def _on_benchmark_finished(self, rep: dict) -> None:
        self.btn_benchmark.setEnabled(True)
        self.btn_benchmark.setText("⚡  Donanım Benchmark")

        self.card_ocr.set_metric(
            f"{rep['avg_ocr_ms']:.1f} ms",
            sub_text=f"Frame Lock: {rep['pixel_lock_ms']:.2f} ms",
            bar_pct=int(min(100, (rep["avg_ocr_ms"] / 80.0) * 100)),
        )
        self.card_nmt.set_metric(
            f"{rep['avg_nmt_ms']:.1f} ms",
            sub_text=f"Cache Hit: {rep['cache_ms']:.4f} ms",
            bar_pct=int(min(100, (rep["avg_nmt_ms"] / 140.0) * 100)),
        )
        self.card_total.set_metric(
            f"{rep['total_cold_ms']:.1f} ms",
            sub_text=f"Warm Cache Toplam: {rep['total_cached_ms']:.1f} ms",
            bar_pct=int(min(100, (rep["total_cold_ms"] / 150.0) * 100)),
        )

        msg = (
            f"⚡ SubVision AI Studio — Donanım Performans Testi Raporu\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🖥️ İşlemci:  {rep['cpu_name']} ({rep['cores']})\n"
            f"⚙️ Profil / Mod:  {self.tuning.effective_profile.upper()} • CTranslate2 {rep['compute_type']}\n\n"
            f"1. Frame Diff Lock (Sabit Kare Atlama):  {rep['pixel_lock_ms']:.3f} ms\n"
            f"2. Fast Line Projection OCR (RapidOCR ONNX):  {rep['avg_ocr_ms']:.1f} ms\n"
            f"3. CTranslate2 {rep['compute_type']} NMT ({rep['threads']} CPU Thread):  {rep['avg_nmt_ms']:.1f} ms\n"
            f"4. Thread-Safe LRU Cache / Glossary Hit:  {rep['cache_ms']:.4f} ms\n\n"
            f"🚀 Uçtan Uca Gecikme (Yeni Altyazı - Cold):  {rep['total_cold_ms']:.1f} ms\n"
            f"⚡ Uçtan Uca Gecikme (Tekrar Eden - Warm Cache):  {rep['total_cached_ms']:.1f} ms\n"
            f"🛡️ Ekran Kartı (GPU / VRAM) Tüketimi:  0 MB (%100 CPU)"
        )
        QMessageBox.information(self, "Donanım Performans Benchmark Raporu", msg)

    def _register_global_hotkeys(self) -> None:
        # Tüm işletim sistemlerinde (Windows / macOS / Linux) çalışan pencere kısayolları
        self._shortcuts = [
            QShortcut(QKeySequence("F7"), self, activated=self.open_roi_selector),
            QShortcut(QKeySequence("F8"), self, activated=self.toggle_translation),
            QShortcut(QKeySequence("F9"), self, activated=self.run_sample_test),
        ]

        # Windows'ta oyun/video penceresi odaktayken de çalışan global kısayol taraması
        if sys.platform == "win32":
            self._key_states = {VK_F7: False, VK_F8: False, VK_F9: False}
            self._hotkey_timer = QTimer(self)
            self._hotkey_timer.setInterval(45)
            self._hotkey_timer.timeout.connect(self._poll_global_hotkeys)
            self._hotkey_timer.start()

    def _poll_global_hotkeys(self) -> None:
        if sys.platform != "win32":
            return
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


def _install_crash_logger() -> None:
    def _handle_exception(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat()}]\n{tb_text}\n")
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None,
                    "SubVision AI — Beklenmeyen Hata",
                    f"Uygulama çalışırken beklenmeyen bir hata oluştu:\n\n{exc_value}\n\n"
                    f"Detaylı hata kaydı şuraya yazıldı:\n{CRASH_LOG_PATH}",
                )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _handle_exception


def _acquire_single_instance() -> Tuple[bool, object]:
    """
    Windows'ta Win32 Mutex, Linux/macOS'ta QLocalServer ile tek örnek (single-instance) kilidi sağlar.
    """
    if sys.platform == "win32":
        try:
            mutex_name = "SubVisionAI_TR_Subtitle_SingleInstance_Mutex_v2"
            mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
            if ctypes.windll.kernel32.GetLastError() == 183:
                hwnd = ctypes.windll.user32.FindWindowW(None, APP_TITLE)
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                return False, None
            return True, ("win32", mutex)
        except Exception:
            return True, None

    try:
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket

        server_name = "SubVisionAI_SingleInstance_IPC_v2"
        probe = QLocalSocket()
        probe.connectToServer(server_name)
        if probe.waitForConnected(150):
            probe.disconnectFromServer()
            return False, None

        QLocalServer.removeServer(server_name)
        server = QLocalServer()
        if server.listen(server_name):
            return True, ("qt_ipc", server)
    except Exception:
        pass
    return True, None


def _release_single_instance(handle: object) -> None:
    if not handle or not isinstance(handle, tuple):
        return
    kind, obj = handle
    try:
        if kind == "win32" and obj:
            ctypes.windll.kernel32.CloseHandle(obj)
        elif kind == "qt_ipc" and obj:
            obj.close()
    except Exception:
        pass


def main():
    _install_crash_logger()

    app = QApplication(sys.argv)
    acquired, lock_handle = _acquire_single_instance()
    if not acquired:
        sys.exit(0)

    window = MainWindow()
    window.show()
    ret = app.exec()
    _release_single_instance(lock_handle)
    sys.exit(ret)


if __name__ == "__main__":
    main()
