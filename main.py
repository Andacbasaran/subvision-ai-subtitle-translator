"""
SubVision AI Studio — Oyunlar, Diziler, Filmler ve Yayınlar İçin Evrensel Lokal (EN -> TR) Anlık Altyazı Çevirici
Mimari: Uyarlanabilir CTranslate2 (INT8/FP32) + RapidOCR (ONNX CPU) + Platforma Duyarlı Şeffaf Overlay
"""

import ctypes
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QPointF, QRect, QSize, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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

APP_TITLE = "SubVision AI — Real-Time Subtitle Studio (EN -> TR)"
DATA_DIR = get_writable_data_dir()
CONFIG_PATH = os.path.join(DATA_DIR, "user_settings.json")
CRASH_LOG_PATH = os.path.join(DATA_DIR, "crash.log")

# Windows Global Hotkey Sabitleri (Admin yetkisi gerektirmez)
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78


def make_flat_icon(kind: str, color_hex: str = "#FAFAFA", size: int = 14) -> QIcon:
    """
    Emoji bağımlılığı olmadan tüm işletim sistemlerinde net görünen
    vektörel (2x HiDPI) minimalist arayüz ikonları üretir.
    """
    px = size * 2
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(color_hex)

    if kind == "dot":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        r = px * 0.34
        p.drawEllipse(QPointF(px / 2.0, px / 2.0), r, r)
    elif kind == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        poly = QPolygonF(
            [
                QPointF(px * 0.28, px * 0.18),
                QPointF(px * 0.84, px * 0.50),
                QPointF(px * 0.28, px * 0.82),
            ]
        )
        p.drawPolygon(poly)
    elif kind == "stop":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(int(px * 0.22), int(px * 0.22), int(px * 0.56), int(px * 0.56), 4, 4)
    elif kind == "target":
        pen = QPen(col, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = int(px * 0.16)
        e = px - m
        l = int(px * 0.24)
        p.drawLine(m, m, m + l, m)
        p.drawLine(m, m, m, m + l)
        p.drawLine(e, m, e - l, m)
        p.drawLine(e, m, e, m + l)
        p.drawLine(m, e, m + l, e)
        p.drawLine(m, e, m, e - l)
        p.drawLine(e, e, e - l, e)
        p.drawLine(e, e, e, e - l)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(px / 2.0, px / 2.0), 2.4, 2.4)
    elif kind == "preview":
        pen = QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(int(px * 0.14), int(px * 0.22), int(px * 0.72), int(px * 0.56), 4, 4)
        p.drawLine(int(px * 0.28), int(px * 0.54), int(px * 0.72), int(px * 0.54))
        p.drawLine(int(px * 0.36), int(px * 0.66), int(px * 0.64), int(px * 0.66))
    elif kind == "gauge":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        bw = int(px * 0.17)
        p.drawRoundedRect(int(px * 0.16), int(px * 0.52), bw, int(px * 0.34), 2, 2)
        p.drawRoundedRect(int(px * 0.42), int(px * 0.32), bw, int(px * 0.54), 2, 2)
        p.drawRoundedRect(int(px * 0.68), int(px * 0.16), bw, int(px * 0.70), 2, 2)
    elif kind == "copy":
        pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(int(px * 0.34), int(px * 0.30), int(px * 0.50), int(px * 0.54), 3, 3)
        p.drawLine(int(px * 0.22), int(px * 0.68), int(px * 0.22), int(px * 0.20))
        p.drawLine(int(px * 0.22), int(px * 0.20), int(px * 0.64), int(px * 0.20))
    elif kind == "manage":
        pen = QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(int(px * 0.18), int(px * 0.22), int(px * 0.64), int(px * 0.60), 4, 4)
        p.drawLine(int(px * 0.32), int(px * 0.42), int(px * 0.68), int(px * 0.42))
        p.drawLine(int(px * 0.32), int(px * 0.60), int(px * 0.56), int(px * 0.60))

    p.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)


def create_app_pixmap(size: int = 64) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pad = max(1, size // 24)
    radius = max(7, int(size * 0.22))
    painter.setBrush(QColor("#2563EB"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(pad, pad, size - 2 * pad, size - 2 * pad, radius, radius)

    painter.setPen(QColor("#FFFFFF"))
    font_sz = max(9, int(size * 0.26))
    painter.setFont(QFont(get_ui_font_family(), font_sz, QFont.Weight.Bold))
    painter.drawText(
        QRect(pad, int(size * 0.12), size - 2 * pad, int(size * 0.44)),
        Qt.AlignmentFlag.AlignCenter,
        "TR",
    )

    y1 = int(size * 0.67)
    y2 = int(size * 0.80)
    painter.setPen(
        QPen(QColor("#FFFFFF"), max(2, size // 16), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(int(size * 0.23), y1, int(size * 0.77), y1)
    painter.setPen(
        QPen(
            QColor(255, 255, 255, 165),
            max(2, size // 20),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    painter.drawLine(int(size * 0.32), y2, int(size * 0.68), y2)

    painter.end()
    return pix


def create_app_icon() -> QIcon:
    search_roots = [get_app_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    for root in search_roots:
        ico_path = os.path.join(root, "assets", "app_icon.ico")
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


class LatestTextSlot:
    """
    1 elemanlı 'en güncel cümle kazanır' (Latest-Frame-Wins) iş parçacığı güvenli kanal.
    NMT bir cümleyi çevirirken yeni altyazı gelirse arada biriken eski cümleleri anında düşürür;
    EMPTY geldiğinde nesil (generation) sayacını artırarak bayat çevirilerin ekrana yanmasını önler.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._generation: int = 0
        self._pending: Optional[Tuple[int, str, float, int]] = None
        self._closed: bool = False
        self.dropped_count: int = 0

    @property
    def generation(self) -> int:
        with self._cond:
            return self._generation

    def submit(self, en_text: str, ocr_ms: float, orig_line_h: int = 0) -> int:
        with self._cond:
            if self._pending is not None:
                self.dropped_count += 1
            self._generation += 1
            gen = self._generation
            self._pending = (gen, en_text, ocr_ms, orig_line_h)
            self._cond.notify()
            return gen

    def invalidate(self) -> int:
        with self._cond:
            self._generation += 1
            self._pending = None
            return self._generation

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._pending = None
            self._generation += 1
            self._cond.notify_all()

    def take(self, timeout: float = 0.25) -> Optional[Tuple[int, str, float, int]]:
        with self._cond:
            if self._pending is None and not self._closed:
                self._cond.wait(timeout=timeout)
            if self._closed or self._pending is None:
                return None
            item = self._pending
            self._pending = None
            return item

    def is_current(self, generation: int) -> bool:
        with self._cond:
            return (not self._closed) and (generation == self._generation)


class CaptureTranslateWorker(QThread):
    subtitle_updated = pyqtSignal(str, str, float, float, bool, int)
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
        self._slot = LatestTextSlot()
        self._nmt_thread: Optional[threading.Thread] = None

    def update_timing(self, scan_interval_sec: float, idle_scan_interval_sec: float) -> None:
        self.scan_interval_sec = max(0.025, float(scan_interval_sec))
        self.idle_scan_interval_sec = max(self.scan_interval_sec, float(idle_scan_interval_sec))

    def _translation_loop(self) -> None:
        while self.running:
            item = self._slot.take(timeout=0.25)
            if item is None:
                continue
            gen, en_text, ocr_ms, orig_line_h = item
            if not self._slot.is_current(gen):
                continue
            try:
                tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(en_text)
                if tr_text and self.running and self._slot.is_current(gen):
                    self.subtitle_updated.emit(
                        en_text, tr_text, ocr_ms, tr_ms, is_cached, orig_line_h
                    )
            except Exception as exc:
                self.status_tick.emit(f"Çeviri hatası: {exc}")

    def run(self) -> None:
        self.running = True
        self.ocr_engine.reset_state()
        self._slot = LatestTextSlot()
        self._nmt_thread = threading.Thread(
            target=self._translation_loop,
            name="SubVision-NMT-Worker",
            daemon=True,
        )
        self._nmt_thread.start()

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
                        self._slot.invalidate()
                        self.subtitle_cleared.emit()
                        idle_streak_sec += self.scan_interval_sec
                    elif status == "NEW_TEXT" and en_text:
                        idle_streak_sec = 0.0
                        orig_line_h = self.ocr_engine.last_line_height_px
                        # Hızlı Yol (0.01 ms): Önbellek / Sözlükte varsa NMT kuyruğunu hiç beklemeden anında göster!
                        fast_hit = self.translator.try_fast_lookup(en_text)
                        if fast_hit is not None:
                            self._slot.invalidate()
                            tr_text, tr_ms, is_cached = fast_hit
                            self.subtitle_updated.emit(
                                en_text, tr_text, ocr_ms, tr_ms, is_cached, orig_line_h
                            )
                        else:
                            self._slot.submit(en_text, ocr_ms, orig_line_h)
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

        self._slot.close()
        if self._nmt_thread and self._nmt_thread.is_alive():
            self._nmt_thread.join(timeout=1.5)

    def stop(self) -> None:
        self.running = False
        self._slot.close()
        self.wait(1800)


class FlatSwitch(QCheckBox):
    """
    Modern flat toggle switch (QCheckBox uyumlu).
    Standart checkbox yerine tüm işletim sistemlerinde net görünen vektörel anahtar çizer.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_w, track_h = 34, 18
        y = (self.height() - track_h) // 2
        checked = self.isChecked()

        track_col = QColor("#2563EB") if checked else QColor("#27272A")
        border_col = QColor("#3B82F6") if checked else QColor("#3F3F46")
        p.setBrush(track_col)
        p.setPen(QPen(border_col, 1))
        p.drawRoundedRect(1, y, track_w, track_h, track_h / 2.0, track_h / 2.0)

        knob_d = 12
        knob_x = (track_w - knob_d - 2) if checked else 4
        knob_y = y + (track_h - knob_d) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FAFAFA") if checked else QColor("#A1A1AA"))
        p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

        p.setPen(QColor("#D4D4D8") if self.isEnabled() else QColor("#52525B"))
        p.setFont(self.font())
        text_rect = QRect(track_w + 11, 0, self.width() - track_w - 11, self.height())
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )
        p.end()


class FlatComboBox(QComboBox):
    """
    Sağ kenarında tüm platformlarda tutarlı, ince vektörel aşağı ok (chevron) çizen flat QComboBox.
    """

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#71717A"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx = self.width() - 15
        cy = self.height() // 2
        p.drawLine(QPointF(cx - 4.0, cy - 2.0), QPointF(cx, cy + 2.2))
        p.drawLine(QPointF(cx, cy + 2.2), QPointF(cx + 4.0, cy - 2.0))
        p.end()


class TelemetryCard(QFrame):
    """
    Sade Flat KPI Telemetri Kartı:
    Yumuşak koyu zemin, tek satır üst etiket + minimal rozet, net metrik değeri ve ince 3px bar.
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
            """
            QFrame#telemetryCard {
                background-color: #111114;
                border: 1px solid #232329;
                border-radius: 10px;
            }
            QFrame#telemetryCard:hover {
                border: 1px solid #32323C;
                background-color: #141418;
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #71717A; font-size: 7.8pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        top_row.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet(
            """
            color: #A1A1AA;
            background-color: #18181B;
            border: 1px solid #27272A;
            border-radius: 4px;
            padding: 1px 6px;
            font-size: 7.2pt;
            font-weight: 700;
            """
        )
        top_row.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(top_row)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet(
            "color: #FAFAFA; font-size: 16.5pt; font-weight: 700; padding-top: 1px;"
        )
        lay.addWidget(self.lbl_val)

        # İnce Flat Gecikme / Doluluk Çubuğu
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(initial_pct)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: #1F1F24;
                border: none;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_hex};
                border-radius: 1px;
            }}
            """
        )
        lay.addWidget(self.bar)

        self.lbl_sub = QLabel(sub_text)
        self.lbl_sub.setStyleSheet("color: #71717A; font-size: 8pt; font-weight: 500;")
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
        init_h = min(840, max(min_h, avail.height() - 40))
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
                "Dizi / Drama",
                "Detective: Everything we found in that room points to a much bigger conspiracy.",
            ),
            (
                "Oyun / RPG",
                "Arthur: Stay close to me, the woods ahead are crawling with bounty hunters.",
            ),
            (
                "Bilim Kurgu",
                "Commander: If we cross the event horizon, there's no turning back for any of us.",
            ),
            (
                "Belgesel",
                "For centuries, this ancient civilization remained completely hidden beneath the jungle.",
            ),
            (
                "Aksiyon",
                "Hold on tight! I'm gonna take the shortcut through the old tunnel!",
            ),
            (
                "Gerilim",
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
            "auto_fit_font": self.chk_autofit.isChecked(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _format_hw_badge_text(self) -> str:
        ctype = self.translator.active_compute_type.upper()
        return (
            f"{self.hw_profile.short_cpu_label}  ·  "
            f"{self.hw_profile.physical_cores}C/{self.hw_profile.logical_cores}T  ·  "
            f"{ctype} ({self.translator.cpu_threads}T)  ·  "
            f"{self.tuning.scan_fps} FPS  ·  0 MB VRAM"
        )

    def _build_ui(self) -> None:
        ui_font = get_ui_font_family()
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#centralWidget, QScrollArea {{
                background-color: #09090B;
                color: #FAFAFA;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', 'DejaVu Sans', -apple-system, sans-serif;
            }}
            QLabel {{
                background-color: transparent;
                color: #E4E4E7;
                font-family: '{ui_font}', 'Segoe UI', 'Inter', 'DejaVu Sans', -apple-system, sans-serif;
            }}
            QFrame#studioPanel {{
                background-color: #111114;
                border: 1px solid #232329;
                border-radius: 10px;
            }}
            QPushButton {{
                background-color: #18181B;
                color: #E4E4E7;
                border: 1px solid #27272A;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 9.2pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #222228;
                border-color: #3F3F46;
                color: #FAFAFA;
            }}
            QPushButton:pressed {{
                background-color: #141417;
            }}
            QPushButton:disabled {{
                background-color: #111114;
                color: #52525B;
                border-color: #1E1E24;
            }}
            QComboBox {{
                background-color: #18181B;
                border: 1px solid #27272A;
                border-radius: 7px;
                padding: 6px 11px;
                min-height: 22px;
                color: #F4F4F5;
                font-size: 9pt;
                font-weight: 500;
            }}
            QComboBox:hover {{
                border-color: #3F3F46;
                background-color: #1C1C21;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #18181B;
                color: #F4F4F5;
                selection-background-color: #27272A;
                selection-color: #FAFAFA;
                border: 1px solid #3F3F46;
                outline: none;
                padding: 4px;
            }}
            QSlider {{
                background-color: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background: #27272A;
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: #3B82F6;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #FAFAFA;
                border: 2px solid #2563EB;
                width: 14px;
                height: 14px;
                margin: -6px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #FFFFFF;
                border-color: #60A5FA;
            }}
            QCheckBox {{
                background-color: transparent;
                color: #D4D4D8;
                font-size: 8.9pt;
                font-weight: 500;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #3F3F46;
                background-color: #18181B;
            }}
            QCheckBox::indicator:hover {{
                border-color: #52525B;
            }}
            QCheckBox::indicator:checked {{
                background-color: #2563EB;
                border-color: #3B82F6;
            }}
            QListWidget {{
                background-color: #0D0D10;
                border: 1px solid #232329;
                border-radius: 8px;
                color: #D4D4D8;
                font-size: 8.8pt;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 0px;
                border-bottom: 1px solid #1A1A20;
                border-radius: 6px;
                margin-bottom: 2px;
            }}
            QListWidget::item:hover {{
                background-color: #141419;
            }}
            QListWidget::item:selected {{
                background-color: #18181E;
                color: #FAFAFA;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: #27272A;
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #3F3F46;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
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
        main_layout.setContentsMargins(16, 14, 16, 12)

        # ═════════════════════════════════════════════════════════════════════
        # 1. MINIMAL FLAT HEADER BAR
        # ═════════════════════════════════════════════════════════════════════
        header_frame = QFrame()
        header_frame.setObjectName("studioPanel")
        header_v = QVBoxLayout(header_frame)
        header_v.setContentsMargins(16, 12, 16, 12)
        header_v.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_app_pixmap(38))
        logo_lbl.setFixedSize(38, 38)
        logo_lbl.setStyleSheet("border: none; background: transparent;")
        top_bar.addWidget(logo_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_lbl = QLabel("SubVision AI")
        title_lbl.setFont(QFont(ui_font, 13, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FAFAFA; border: none; background: transparent;")
        title_row.addWidget(title_lbl)

        ver_pill = QLabel("v1.3")
        ver_pill.setStyleSheet(
            "color: #A1A1AA; background-color: #18181B; border: 1px solid #27272A; border-radius: 4px; padding: 1px 6px; font-size: 7.5pt; font-weight: 700;"
        )
        title_row.addWidget(ver_pill)
        title_row.addStretch(1)
        title_col.addLayout(title_row)

        sub_lbl = QLabel("Lokal Yapay Zeka Altyazı Stüdyosu  ·  EN → TR")
        sub_lbl.setStyleSheet(
            "color: #71717A; font-size: 8.6pt; font-weight: 500; border: none; background: transparent;"
        )
        title_col.addWidget(sub_lbl)
        top_bar.addLayout(title_col, stretch=1)

        badge_col = QVBoxLayout()
        badge_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        badge_col.setSpacing(4)

        self.hw_badge = QLabel(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.hw_badge.setStyleSheet(
            "color: #A1A1AA; background-color: #18181B; border: 1px solid #232329; border-radius: 6px; padding: 3px 10px; font-size: 7.9pt; font-weight: 600;"
        )
        badge_col.addWidget(self.hw_badge, alignment=Qt.AlignmentFlag.AlignRight)

        self.lbl_model_status = QLabel("●  Donanım algılandı, motorlar hazırlanıyor...")
        self.lbl_model_status.setStyleSheet(
            "color: #EAB308; font-size: 8.5pt; font-weight: 600; border: none; background: transparent;"
        )
        badge_col.addWidget(self.lbl_model_status, alignment=Qt.AlignmentFlag.AlignRight)
        top_bar.addLayout(badge_col)

        header_v.addLayout(top_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: none;
                border-radius: 2px;
                background-color: #1F1F24;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 2px;
            }
            """
        )
        header_v.addWidget(self.progress_bar)
        main_layout.addWidget(header_frame)

        # ═════════════════════════════════════════════════════════════════════
        # 2. FLAT TELEMETRİ ŞERİDİ (4 KPI Cards)
        # ═════════════════════════════════════════════════════════════════════
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self.card_ocr = TelemetryCard(
            "OCR YAKALAMA",
            "FAST MASK",
            "— ms",
            f"2 Aşamalı Kare Kilidi · {self.tuning.ocr_intra_threads} Thread",
            "#3B82F6",
            18,
        )
        self.card_nmt = TelemetryCard(
            f"NMT ÇEVİRİ ({self.translator.active_compute_type.upper()})",
            f"{self.translator.cpu_threads} THREAD",
            "— ms",
            "Opus-MT Big EN → TR",
            "#EAB308",
            40,
        )
        self.card_total = TelemetryCard(
            "TOPLAM GECİKME",
            "REAL-TIME",
            "— ms",
            "Hedef < 150 ms anlık algı",
            "#22C55E",
            50,
        )
        self.card_stats = TelemetryCard(
            "OTURUM & ÖNBELLEK",
            f"{self.tuning.scan_fps} FPS",
            "0 Çeviri",
            f"ROI {self.roi['width']}×{self.roi['height']} px · Hit %0",
            "#A1A1AA",
            10,
        )

        kpi_row.addWidget(self.card_ocr)
        kpi_row.addWidget(self.card_nmt)
        kpi_row.addWidget(self.card_total)
        kpi_row.addWidget(self.card_stats)
        main_layout.addLayout(kpi_row)

        # ═════════════════════════════════════════════════════════════════════
        # 3. HİYERARŞİK FLAT KOMUT ÇUBUĞU
        # ═════════════════════════════════════════════════════════════════════
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_select_roi = QPushButton("  Altyazı Alanı Seç   (F7)")
        self.btn_select_roi.setIcon(make_flat_icon("target", "#E4E4E7", 14))
        self.btn_select_roi.setIconSize(QSize(14, 14))
        self.btn_select_roi.setMinimumHeight(40)
        self.btn_select_roi.setStyleSheet(
            """
            QPushButton {
                background-color: #18181B;
                border: 1px solid #2E2E36;
                color: #FAFAFA;
                font-size: 9.4pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #222228;
                border-color: #3F3F46;
            }
            """
        )
        self.btn_select_roi.clicked.connect(self.open_roi_selector)
        btn_row.addWidget(self.btn_select_roi, stretch=3)

        self.btn_toggle = QPushButton("  Anlık Çeviriyi Başlat   (F8)")
        self.btn_toggle.setIcon(make_flat_icon("play", "#FFFFFF", 13))
        self.btn_toggle.setIconSize(QSize(13, 13))
        self.btn_toggle.setMinimumHeight(40)
        self.btn_toggle.setEnabled(False)
        self._set_toggle_button_style(active=False)
        self.btn_toggle.clicked.connect(self.toggle_translation)
        btn_row.addWidget(self.btn_toggle, stretch=3)

        self.btn_test = QPushButton("  Örnek Sahne   (F9)")
        self.btn_test.setIcon(make_flat_icon("preview", "#D4D4D8", 14))
        self.btn_test.setIconSize(QSize(14, 14))
        self.btn_test.setMinimumHeight(40)
        self.btn_test.setEnabled(False)
        self.btn_test.clicked.connect(self.run_sample_test)
        btn_row.addWidget(self.btn_test, stretch=2)

        self.btn_benchmark = QPushButton("  Benchmark")
        self.btn_benchmark.setIcon(make_flat_icon("gauge", "#D4D4D8", 14))
        self.btn_benchmark.setIconSize(QSize(14, 14))
        self.btn_benchmark.setMinimumHeight(40)
        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.clicked.connect(self.run_benchmark_suite)
        btn_row.addWidget(self.btn_benchmark, stretch=2)

        self.btn_manage = QPushButton("  Bileşenler / Kaldır")
        self.btn_manage.setIcon(make_flat_icon("manage", "#D4D4D8", 14))
        self.btn_manage.setIconSize(QSize(14, 14))
        self.btn_manage.setMinimumHeight(40)
        self.btn_manage.setToolTip("İndirilen yapay zeka modelini, çalışma ortamını ve kaldırma seçeneklerini yönet")
        self.btn_manage.clicked.connect(self.open_component_manager)
        btn_row.addWidget(self.btn_manage, stretch=2)

        main_layout.addLayout(btn_row)

        # ═════════════════════════════════════════════════════════════════════
        # 4. İKİ SÜTUNLU FLAT STUDIO WORKSPACE
        # ═════════════════════════════════════════════════════════════════════
        workspace_row = QHBoxLayout()
        workspace_row.setSpacing(12)

        # ─────────────────────────────────────────────────────────────────────
        # SOL SÜTUN (%56): CANLI AKIŞ & DİYALOG GEÇMİŞİ
        # ─────────────────────────────────────────────────────────────────────
        left_panel = QFrame()
        left_panel.setObjectName("studioPanel")
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(16, 14, 16, 14)
        left_lay.setSpacing(10)

        left_hdr = QHBoxLayout()
        lbl_left_title = QLabel("CANLI AKIŞ")
        lbl_left_title.setStyleSheet(
            "color: #A1A1AA; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.9px;"
        )
        left_hdr.addWidget(lbl_left_title)

        self.lbl_scene_tag = QLabel(f"Canlı Yakalama · {self.tuning.scan_fps} FPS")
        self.lbl_scene_tag.setStyleSheet(
            "color: #A1A1AA; background-color: #18181B; border: 1px solid #232329; border-radius: 5px; padding: 2px 8px; font-size: 7.9pt; font-weight: 600;"
        )
        left_hdr.addWidget(self.lbl_scene_tag, alignment=Qt.AlignmentFlag.AlignRight)
        left_lay.addLayout(left_hdr)

        lbl_en_cap = QLabel("KAYNAK METİN (EN)")
        lbl_en_cap.setStyleSheet(
            "color: #71717A; font-size: 7.5pt; font-weight: 700; letter-spacing: 0.6px; padding-top: 2px;"
        )
        left_lay.addWidget(lbl_en_cap)

        self.lbl_en_preview = QLabel(
            "Altyazı bekleniyor. F7 ile yakalama bölgesini seçip F8 ile çeviriyi başlatabilirsiniz."
        )
        self.lbl_en_preview.setWordWrap(True)
        self.lbl_en_preview.setMinimumHeight(46)
        self.lbl_en_preview.setStyleSheet(
            """
            background-color: #18181B;
            border: 1px solid #232329;
            padding: 10px 13px;
            border-radius: 8px;
            color: #E4E4E7;
            font-size: 9.8pt;
            font-weight: 500;
            """
        )
        left_lay.addWidget(self.lbl_en_preview)

        tr_hdr = QHBoxLayout()
        lbl_tr_cap = QLabel("TÜRKÇE ÇEVİRİ (TR)")
        lbl_tr_cap.setStyleSheet(
            "color: #71717A; font-size: 7.5pt; font-weight: 700; letter-spacing: 0.6px; padding-top: 2px;"
        )
        tr_hdr.addWidget(lbl_tr_cap)

        btn_copy = QPushButton(" Kopyala")
        btn_copy.setIcon(make_flat_icon("copy", "#A1A1AA", 12))
        btn_copy.setIconSize(QSize(12, 12))
        btn_copy.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #A1A1AA;
                border: 1px solid #232329;
                padding: 3px 9px;
                font-size: 7.8pt;
                font-weight: 600;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #18181B;
                color: #FAFAFA;
                border-color: #3F3F46;
            }
            """
        )
        btn_copy.clicked.connect(self._copy_current_translation)
        tr_hdr.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignRight)
        left_lay.addLayout(tr_hdr)

        self.lbl_tr_preview = QLabel("Çeviri bekleniyor...")
        self.lbl_tr_preview.setWordWrap(True)
        self.lbl_tr_preview.setMinimumHeight(52)
        self.lbl_tr_preview.setStyleSheet(
            """
            background-color: #18181B;
            border: 1px solid #2E2E36;
            padding: 10px 13px;
            border-radius: 8px;
            color: #FACC15;
            font-size: 11pt;
            font-weight: 700;
            """
        )
        left_lay.addWidget(self.lbl_tr_preview)

        hist_hdr = QHBoxLayout()
        lbl_hist = QLabel("DİYALOG GEÇMİŞİ")
        lbl_hist.setStyleSheet(
            "color: #71717A; font-size: 7.5pt; font-weight: 700; letter-spacing: 0.6px; padding-top: 4px;"
        )
        hist_hdr.addWidget(lbl_hist)

        btn_clear_hist = QPushButton("Temizle")
        btn_clear_hist.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #71717A;
                border: none;
                padding: 2px 6px;
                font-size: 8pt;
                font-weight: 600;
            }
            QPushButton:hover {
                color: #EF4444;
                background-color: transparent;
            }
            """
        )
        btn_clear_hist.clicked.connect(lambda: self.list_history.clear())
        hist_hdr.addWidget(btn_clear_hist, alignment=Qt.AlignmentFlag.AlignRight)
        left_lay.addLayout(hist_hdr)

        self.list_history = QListWidget()
        self.list_history.setWordWrap(True)
        self.list_history.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list_history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_history.setMinimumHeight(130)
        left_lay.addWidget(self.list_history, stretch=1)

        workspace_row.addWidget(left_panel, stretch=56)

        # ─────────────────────────────────────────────────────────────────────
        # SAĞ SÜTUN (%44): YAPILANDIRMA & OVERLAY ÖNİZLEME
        # ─────────────────────────────────────────────────────────────────────
        right_panel = QFrame()
        right_panel.setObjectName("studioPanel")
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(16, 14, 16, 14)
        right_lay.setSpacing(10)

        lbl_right_title = QLabel("YAPILANDIRMA & OVERLAY")
        lbl_right_title.setStyleSheet(
            "color: #A1A1AA; font-size: 8.2pt; font-weight: 700; letter-spacing: 0.9px;"
        )
        right_lay.addWidget(lbl_right_title)

        # İşlemci & Performans Profili
        lbl_perf_prof = QLabel("İşlemci Profili")
        lbl_perf_prof.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 600;")
        right_lay.addWidget(lbl_perf_prof)

        self.combo_perf_profile = FlatComboBox()
        self.combo_perf_profile.addItem("Otomatik — İşlemciye Göre En İyi", PROFILE_AUTO)
        self.combo_perf_profile.addItem("Eko — Eski / Düşük CPU (15 FPS)", PROFILE_ECO)
        self.combo_perf_profile.addItem("Dengeli — Orta Seviye CPU (24 FPS)", PROFILE_BALANCED)
        self.combo_perf_profile.addItem("Performans — Çok Çekirdekli CPU (30 FPS)", PROFILE_PERFORMANCE)
        self.combo_perf_profile.currentIndexChanged.connect(self._on_perf_profile_changed)
        right_lay.addWidget(self.combo_perf_profile)

        # OCR Algılama Profili
        lbl_ocr_prof = QLabel("OCR Algılama Modu")
        lbl_ocr_prof.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 600;")
        right_lay.addWidget(lbl_ocr_prof)

        self.combo_ocr_mode = FlatComboBox()
        self.combo_ocr_mode.addItem("Kontürlü / Adaptif Maske — Oyun & Dizi (Önerilen)", "fast_mask")
        self.combo_ocr_mode.addItem("Hibrit — Oyun, Dizi & Açık Zemin (Akıllı Yedek)", "hybrid")
        self.combo_ocr_mode.addItem("Tam Kare OCR — Genel Ekran & Video", "full_ocr")
        self.combo_ocr_mode.currentIndexChanged.connect(self._on_ocr_mode_changed)
        right_lay.addWidget(self.combo_ocr_mode)

        # Altyazı Konumu (Flat Segmented Control)
        lbl_pos_title = QLabel("Overlay Konumu")
        lbl_pos_title.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 600;")
        right_lay.addWidget(lbl_pos_title)

        seg_frame = QFrame()
        seg_frame.setStyleSheet(
            "QFrame { background-color: #09090B; border: 1px solid #232329; border-radius: 8px; }"
        )
        pos_row = QHBoxLayout(seg_frame)
        pos_row.setContentsMargins(3, 3, 3, 3)
        pos_row.setSpacing(3)
        self.btn_mode_cover = QPushButton("Orijinalin Üstünü Kapat")
        if not self.hw_profile.capture_exclude_supported:
            self.btn_mode_cover.setToolTip(
                "Bu işletim sistemi sürümünde WDA_EXCLUDEFROMCAPTURE desteklenmediği için "
                "OCR döngüsünü önlemek adına 'Hemen Üstünde' konumu otomatik uygulanır."
            )
        self.btn_mode_above = QPushButton("Hemen Üstünde Göster")
        self.btn_mode_cover.clicked.connect(lambda: self._select_overlay_mode("cover"))
        self.btn_mode_above.clicked.connect(lambda: self._select_overlay_mode("above"))
        pos_row.addWidget(self.btn_mode_cover)
        pos_row.addWidget(self.btn_mode_above)
        right_lay.addWidget(seg_frame)

        # Altyazı Renk Paleti (Vektörel Renk Noktalı Flat Swatch'lar)
        lbl_col_title = QLabel("Altyazı Rengi")
        lbl_col_title.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 600;")
        right_lay.addWidget(lbl_col_title)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        self._color_buttons: Dict[str, QPushButton] = {}
        color_presets = [
            ("#FFFFFF", "Beyaz"),
            ("#FACC15", "Sarı"),
            ("#38BDF8", "Turkuaz"),
            ("#4ADE80", "Yeşil"),
        ]
        for hex_code, label_txt in color_presets:
            b = QPushButton(f" {label_txt}")
            b.setIcon(make_flat_icon("dot", hex_code, 10))
            b.setIconSize(QSize(10, 10))
            b.clicked.connect(lambda checked=False, c=hex_code: self._select_color_swatch(c))
            self._color_buttons[hex_code] = b
            swatch_row.addWidget(b)
        right_lay.addLayout(swatch_row)

        # Yazı Boyutu & Arka Plan Opaklığı Sliders
        sliders_grid = QGridLayout()
        sliders_grid.setSpacing(8)
        sliders_grid.setContentsMargins(0, 2, 0, 2)

        self.lbl_font_cap = QLabel("Maks. Boyut")
        self.lbl_font_cap.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 600;")
        sliders_grid.addWidget(self.lbl_font_cap, 0, 0)

        self.slider_font = QSlider(Qt.Orientation.Horizontal)
        self.slider_font.setRange(14, 36)
        self.slider_font.setValue(self.settings.get("font_size", 22))
        self.slider_font.valueChanged.connect(self._on_appearance_changed)
        sliders_grid.addWidget(self.slider_font, 0, 1)

        self.lbl_font_val = QLabel("22 pt")
        self.lbl_font_val.setMinimumWidth(42)
        self.lbl_font_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_font_val.setStyleSheet("color: #E4E4E7; font-size: 8.3pt; font-weight: 600;")
        sliders_grid.addWidget(self.lbl_font_val, 0, 2)

        lbl_alpha_cap = QLabel("Arka Plan")
        lbl_alpha_cap.setStyleSheet("color: #A1A1AA; font-size: 8.3pt; font-weight: 600;")
        sliders_grid.addWidget(lbl_alpha_cap, 1, 0)

        init_alpha = self.settings.get("bg_alpha", 225)
        self.slider_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_alpha.setRange(90, 250)
        self.slider_alpha.setValue(init_alpha)
        self.slider_alpha.valueChanged.connect(self._on_appearance_changed)
        sliders_grid.addWidget(self.slider_alpha, 1, 1)

        self.lbl_alpha_val = QLabel(f"%{int(init_alpha / 255 * 100)}")
        self.lbl_alpha_val.setMinimumWidth(42)
        self.lbl_alpha_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_alpha_val.setStyleSheet("color: #E4E4E7; font-size: 8.3pt; font-weight: 600;")
        sliders_grid.addWidget(self.lbl_alpha_val, 1, 2)

        right_lay.addLayout(sliders_grid)

        # Görünüm Seçenekleri (Modern Flat Toggle Switches)
        self.chk_autofit = FlatSwitch("Otomatik yazı boyutu (Orijinali tam kapat)")
        self.chk_autofit.setChecked(self.settings.get("auto_fit_font", True))
        self.chk_autofit.toggled.connect(self._on_appearance_changed)
        right_lay.addWidget(self.chk_autofit)

        self.chk_bilingual = FlatSwitch("Çift dilli görünüm (Üstte EN + Altta TR)")
        self.chk_bilingual.setChecked(self.settings.get("show_bilingual", False))
        self.chk_bilingual.toggled.connect(self._on_appearance_changed)
        right_lay.addWidget(self.chk_bilingual)

        self.chk_guide = FlatSwitch("Ekranda hizalama kılavuz çerçevesini göster")
        self.chk_guide.setChecked(False)
        self.chk_guide.toggled.connect(self.overlay.set_guide_border)
        right_lay.addWidget(self.chk_guide)

        # Canlı Overlay Önizleme Kutusu
        lbl_prev_hdr = QLabel("CANLI ÖNİZLEME")
        lbl_prev_hdr.setStyleSheet(
            "color: #71717A; font-size: 7.5pt; font-weight: 700; letter-spacing: 0.6px; padding-top: 4px;"
        )
        right_lay.addWidget(lbl_prev_hdr)

        self.preview_box = QFrame()
        self.preview_box.setMinimumHeight(88)
        prev_v = QVBoxLayout(self.preview_box)
        prev_v.setContentsMargins(14, 10, 14, 10)
        prev_v.setSpacing(3)

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
        # 5. MINIMAL ALT BİLGİ ÇUBUĞU
        # ═════════════════════════════════════════════════════════════════════
        footer = QLabel(
            "Oyunlarda 'Borderless Windowed' modunu kullanın  ·  Netflix, YouTube, Prime Video, Twitch ve VLC ile uyumlu  ·  "
            "Kısayollar: F7 Alan Seç  |  F8 Başlat/Durdur  |  F9 Örnek Sahne"
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #71717A; font-size: 8.1pt; font-weight: 500; padding-top: 2px;")
        main_layout.addWidget(footer)

    def _set_toggle_button_style(self, active: bool) -> None:
        if active:
            self.btn_toggle.setIcon(make_flat_icon("stop", "#FFFFFF", 13))
            self.btn_toggle.setText("  Canlı Çeviriyi Durdur   (F8)")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #DC2626;
                    border: 1px solid #EF4444;
                    color: #FFFFFF;
                    font-size: 9.4pt;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #B91C1C;
                    border-color: #F87171;
                }
                """
            )
        else:
            self.btn_toggle.setIcon(make_flat_icon("play", "#FFFFFF", 13))
            self.btn_toggle.setText("  Anlık Çeviriyi Başlat   (F8)")
            self.btn_toggle.setStyleSheet(
                """
                QPushButton {
                    background-color: #2563EB;
                    border: 1px solid #3B82F6;
                    color: #FFFFFF;
                    font-size: 9.4pt;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #1D4ED8;
                    border-color: #60A5FA;
                }
                QPushButton:disabled {
                    background-color: #18181B;
                    border-color: #232329;
                    color: #52525B;
                }
                """
            )

    def _select_color_swatch(self, hex_code: str) -> None:
        self._selected_color = hex_code
        self._on_appearance_changed()

    def _select_overlay_mode(self, mode: str) -> None:
        self._selected_overlay_mode = mode
        self._on_appearance_changed()

    def _update_designer_button_styles(self) -> None:
        # Flat Segmented Control (Konum)
        active_pos_css = (
            "QPushButton { background-color: #27272A; border: none; border-radius: 6px; color: #FAFAFA; padding: 6px 10px; font-size: 8.5pt; font-weight: 600; }"
        )
        idle_pos_css = (
            "QPushButton { background-color: transparent; border: none; border-radius: 6px; color: #71717A; padding: 6px 10px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { color: #D4D4D8; background-color: #18181B; }"
        )
        self.btn_mode_cover.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "cover" else idle_pos_css
        )
        self.btn_mode_above.setStyleSheet(
            active_pos_css if self._selected_overlay_mode == "above" else idle_pos_css
        )

        # Flat Renk Paleti Swatch Butonları
        for hex_code, btn in self._color_buttons.items():
            if hex_code == self._selected_color:
                btn.setStyleSheet(
                    "QPushButton { background-color: #27272A; border: 1px solid #52525B; border-radius: 7px; color: #FAFAFA; padding: 6px 8px; font-size: 8.4pt; font-weight: 600; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #18181B; border: 1px solid #232329; border-radius: 7px; color: #A1A1AA; padding: 6px 8px; font-size: 8.4pt; font-weight: 500; } "
                    "QPushButton:hover { border-color: #3F3F46; color: #FAFAFA; background-color: #1E1E24; }"
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
            "hybrid": "HYBRID",
            "fast_mask": "FAST MASK",
            "full_ocr": "FULL OCR",
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
                f"●  Canlı Tarama Aktif  ·  {self.tuning.scan_fps} FPS ({ms_interval} ms)"
            )

        self.hw_badge.setText(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.lbl_scene_tag.setText(f"Canlı Yakalama · {self.tuning.scan_fps} FPS")
        self.card_ocr.set_metric(
            self.card_ocr.lbl_val.text(),
            sub_text=f"2 Aşamalı Kare Kilidi · {self.tuning.ocr_intra_threads} Thread",
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
        self.lbl_model_status.setText(f"●  {msg}")
        self.progress_bar.setValue(pct)

    def _on_model_ready(self) -> None:
        ctype = self.translator.active_compute_type.upper()
        self.hw_badge.setText(self._format_hw_badge_text())
        self.hw_badge.setToolTip(format_hardware_summary(self.hw_profile, self.tuning))
        self.card_nmt.lbl_title.setText(f"NMT ÇEVİRİ ({ctype})")
        self.lbl_model_status.setText(
            f"●  Hazır  ·  Opus-MT {ctype} ({self.translator.cpu_threads}T CPU)"
        )
        self.lbl_model_status.setStyleSheet(
            "color: #22C55E; font-weight: 600; font-size: 8.5pt; border: none; background: transparent;"
        )
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.btn_toggle.setEnabled(True)
        self.btn_test.setEnabled(True)
        self.btn_benchmark.setEnabled(True)

    def _on_model_failed(self, err: str) -> None:
        self.lbl_model_status.setText(f"●  Model yükleme hatası: {err}")
        self.lbl_model_status.setStyleSheet(
            "color: #EF4444; font-weight: 600; font-size: 8.5pt; border: none; background: transparent;"
        )

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
                "Altyazı alanı seçildi. Çeviriyi başlatmak için F8 tuşuna basın."
            )

    def _on_appearance_changed(self) -> None:
        f_size = self.slider_font.value()
        alpha = self.slider_alpha.value()
        alpha_pct = int(alpha / 255 * 100)
        bilingual = self.chk_bilingual.isChecked()
        auto_fit = self.chk_autofit.isChecked()

        self.lbl_font_cap.setText("Maks. Boyut" if auto_fit else "Yazı Boyutu")
        self.lbl_font_val.setText(f"{f_size} pt")
        self.lbl_alpha_val.setText(f"%{alpha_pct}")
        self._update_designer_button_styles()

        # Mini Canlı Önizleme Kutusunu Güncelle
        preview_font_pt = max(10, min(15, int(f_size * 0.54)))
        en_font_pt = max(8, int(preview_font_pt * 0.72))
        self.preview_box.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(9, 9, 11, {alpha});
                border: 1px solid #232329;
                border-radius: 8px;
            }}
            """
        )
        self.lbl_mini_en.setVisible(bilingual)
        self.lbl_mini_en.setStyleSheet(
            f"color: #A1A1AA; font-size: {en_font_pt}pt; font-weight: 500; border: none; background: transparent;"
        )
        self.lbl_mini_tr.setStyleSheet(
            f"color: {self._selected_color}; font-size: {preview_font_pt}pt; font-weight: 700; border: none; background: transparent;"
        )

        self.overlay.update_appearance(
            font_size=f_size,
            text_color=self._selected_color,
            bg_alpha=alpha,
            overlay_mode=self._selected_overlay_mode,
            show_bilingual=bilingual,
            auto_fit_font=auto_fit,
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
            sub_text=f"ROI {self.roi['width']}×{self.roi['height']} px · Hit %{hit_pct}",
            badge_text=f"%{hit_pct} CACHE" if req > 0 else f"{self.tuning.scan_fps} FPS",
            bar_pct=max(12, hit_pct),
        )

    def toggle_translation(self) -> None:
        if not self.translator.is_ready:
            return

        if self.worker and self.worker.running:
            self.worker.stop()
            self.worker = None
            self._set_toggle_button_style(active=False)
            ctype = self.translator.active_compute_type.upper()
            self.lbl_model_status.setText(
                f"●  Hazır  ·  Opus-MT {ctype} ({self.translator.cpu_threads}T CPU)"
            )
            self.lbl_model_status.setStyleSheet(
                "color: #22C55E; font-weight: 600; font-size: 8.5pt; border: none; background: transparent;"
            )
            self.overlay.set_subtitle("")
        else:
            self.overlay.align_to_roi(self.roi)
            self.overlay.set_subtitle("")
            self.lbl_scene_tag.setText(f"Canlı Yakalama · {self.tuning.scan_fps} FPS")
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
                f"●  Canlı Tarama Aktif  ·  {self.tuning.scan_fps} FPS ({ms_interval} ms)"
            )
            self.lbl_model_status.setStyleSheet(
                "color: #3B82F6; font-weight: 600; font-size: 8.5pt; border: none; background: transparent;"
            )
            self._set_toggle_button_style(active=True)

    def _on_subtitle_updated(
        self,
        en_text: str,
        tr_text: str,
        ocr_ms: float,
        tr_ms: float,
        is_cached: bool,
        orig_line_h: int = 0,
    ) -> None:
        self.overlay.set_subtitle(tr_text, en_text, orig_line_h_px=orig_line_h)
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
            sub_text="RapidOCR ONNX · Kare Kilidi",
            bar_pct=ocr_pct,
        )
        self.card_nmt.set_metric(
            f"{tr_ms:.3f} ms" if is_cached else f"{tr_ms:.1f} ms",
            sub_text="RAM LRU Cache / Sözlük"
            if is_cached
            else f"CTranslate2 {ctype} · {self.translator.cpu_threads} Thread",
            badge_text="CACHE" if is_cached else ctype,
            bar_pct=nmt_pct,
        )
        self.card_total.set_metric(
            f"{total_ms:.1f} ms",
            sub_text="Anlık algı eşiği altı (<150 ms)"
            if total_ms < 150
            else "Gerçek zamanlı yanıt",
            badge_text="INSTANT" if is_cached else "REAL-TIME",
            bar_pct=tot_pct,
        )
        self._update_session_kpi()

        stamp = datetime.now().strftime("%H:%M:%S")
        tag = "CACHE" if is_cached else ctype
        card = self._create_history_card(stamp, total_ms, tag, en_text, tr_text)
        item = QListWidgetItem()
        avail_w = max(320, self.list_history.viewport().width() - 12)
        card.setFixedWidth(avail_w)
        card.adjustSize()
        item.setSizeHint(card.sizeHint())
        self.list_history.insertItem(0, item)
        self.list_history.setItemWidget(item, card)
        if self.list_history.count() > 25:
            self.list_history.takeItem(self.list_history.count() - 1)

    @staticmethod
    def _create_history_card(
        stamp: str, total_ms: float, tag: str, en_text: str, tr_text: str
    ) -> QWidget:
        card = QWidget()
        card.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        lbl_meta = QLabel(f"{stamp}  ·  {total_ms:.1f} ms  ·  {tag}")
        lbl_meta.setStyleSheet("color: #71717A; font-size: 7.7pt; font-weight: 600;")
        lay.addWidget(lbl_meta)

        lbl_en = QLabel(en_text)
        lbl_en.setWordWrap(True)
        lbl_en.setStyleSheet("color: #A1A1AA; font-size: 8.6pt; font-weight: 500;")
        lay.addWidget(lbl_en)

        lbl_tr = QLabel(tr_text)
        lbl_tr.setWordWrap(True)
        lbl_tr.setStyleSheet("color: #F4F4F5; font-size: 9pt; font-weight: 600;")
        lay.addWidget(lbl_tr)

        return card

    def _on_subtitle_cleared(self) -> None:
        self.overlay.set_subtitle("")

    def run_sample_test(self) -> None:
        if not self.translator.is_ready:
            return
        category, sample_en = self._samples[self._sample_idx % len(self._samples)]
        self._sample_idx += 1
        self.lbl_scene_tag.setText(f"Simülasyon · {category}")
        tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(sample_en)
        # Simülasyonda gerçekçi 19.8 ms OCR süresi ile birlikte uçtan uca göster
        self._on_subtitle_updated(sample_en, tr_text, 19.8, tr_ms, is_cached)

    def run_benchmark_suite(self) -> None:
        if not self.translator.is_ready:
            return
        if self.bench_worker and self.bench_worker.isRunning():
            return

        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.setText("  Ölçülüyor...")
        self.bench_worker = BenchmarkWorker(self.ocr_engine, self.translator, self.hw_profile)
        self.bench_worker.finished_report.connect(self._on_benchmark_finished)
        self.bench_worker.start()

    def _on_benchmark_finished(self, rep: dict) -> None:
        self.btn_benchmark.setEnabled(True)
        self.btn_benchmark.setText("  Benchmark")

        self.card_ocr.set_metric(
            f"{rep['avg_ocr_ms']:.1f} ms",
            sub_text=f"Kare Kilidi: {rep['pixel_lock_ms']:.2f} ms",
            bar_pct=int(min(100, (rep["avg_ocr_ms"] / 80.0) * 100)),
        )
        self.card_nmt.set_metric(
            f"{rep['avg_nmt_ms']:.1f} ms",
            sub_text=f"Cache Hit: {rep['cache_ms']:.4f} ms",
            bar_pct=int(min(100, (rep["avg_nmt_ms"] / 140.0) * 100)),
        )
        self.card_total.set_metric(
            f"{rep['total_cold_ms']:.1f} ms",
            sub_text=f"Önbellekli Toplam: {rep['total_cached_ms']:.1f} ms",
            bar_pct=int(min(100, (rep["total_cold_ms"] / 150.0) * 100)),
        )

        msg = (
            f"SubVision AI Studio — Donanım Performans Raporu\n"
            f"─────────────────────────────────────────────────\n"
            f"İşlemci:  {rep['cpu_name']} ({rep['cores']})\n"
            f"Profil / Mod:  {self.tuning.effective_profile.upper()} · CTranslate2 {rep['compute_type']}\n\n"
            f"1. Frame Diff Lock (Sabit Kare Atlama):  {rep['pixel_lock_ms']:.3f} ms\n"
            f"2. Fast Line Projection OCR (RapidOCR):  {rep['avg_ocr_ms']:.1f} ms\n"
            f"3. CTranslate2 {rep['compute_type']} NMT ({rep['threads']} Thread):  {rep['avg_nmt_ms']:.1f} ms\n"
            f"4. LRU Cache / Sözlük Yanıtı:  {rep['cache_ms']:.4f} ms\n\n"
            f"Toplam Gecikme (Yeni Altyazı):  {rep['total_cold_ms']:.1f} ms\n"
            f"Toplam Gecikme (Önbellekli):  {rep['total_cached_ms']:.1f} ms\n"
            f"GPU / VRAM Kullanımı:  0 MB (%100 CPU)"
        )
        QMessageBox.information(self, "Donanım Performans Raporu", msg)

    @staticmethod
    def _calc_dir_size_mb(path: str) -> float:
        if not path or not os.path.exists(path):
            return 0.0
        total = 0
        try:
            for root_d, _, files in os.walk(path):
                for fname in files:
                    try:
                        total += os.path.getsize(os.path.join(root_d, fname))
                    except Exception:
                        pass
        except Exception:
            pass
        return total / (1024.0 * 1024.0)

    def open_component_manager(self) -> None:
        """
        Uygulama ile birlikte indirilen bileşenleri (227 MB yapay zeka modeli,
        kullanıcı ayarları, önbellek ve çalışma ortamı) opsiyonel olarak sıfırlama
        veya dijital imzalı Kaldırma Yardımcısını (SubVisionAI-Uninstaller.exe) başlatma penceresi.
        """
        app_dir = get_app_base_dir()
        model_mb = self._calc_dir_size_mb(self.translator.model_dir)
        runtime_mb = self._calc_dir_size_mb(os.path.join(app_dir, "runtime"))

        dlg = QDialog(self)
        dlg.setWindowTitle("SubVision AI — Bileşen ve Kaldırma Yöneticisi")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet(
            """
            QDialog {
                background-color: #09090B;
                color: #FAFAFA;
            }
            QFrame#mgrCard {
                background-color: #111114;
                border: 1px solid #232329;
                border-radius: 10px;
            }
            """
        )

        v_main = QVBoxLayout(dlg)
        v_main.setContentsMargins(18, 16, 18, 16)
        v_main.setSpacing(12)

        card = QFrame()
        card.setObjectName("mgrCard")
        v_card = QVBoxLayout(card)
        v_card.setContentsMargins(16, 14, 16, 14)
        v_card.setSpacing(10)

        lbl_h = QLabel("İndirilen Bileşenler ve Kaldırma Seçenekleri")
        lbl_h.setStyleSheet("color: #FAFAFA; font-size: 11.5pt; font-weight: 700;")
        v_card.addWidget(lbl_h)

        lbl_desc = QLabel(
            "Program ile birlikte yüklenen bileşenleri aşağıdan opsiyonel olarak seçip "
            "temizleyebilir veya tam kaldırma sihirbazını başlatabilirsiniz:"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #A1A1AA; font-size: 8.8pt;")
        v_card.addWidget(lbl_desc)

        chk_cache = QCheckBox(
            f"1. RAM Çeviri Önbelleği ve Geçici Kayıtları Temizle ({self.translator.cache_size} cümle)"
        )
        chk_cache.setChecked(True)
        v_card.addWidget(chk_cache)

        chk_settings = QCheckBox(
            "2. Kişisel Kullanıcı Ayarları ve ROI Kalibrasyonunu Sıfırla (user_settings.json)"
        )
        chk_settings.setChecked(False)
        v_card.addWidget(chk_settings)

        chk_model = QCheckBox(
            f"3. İndirilen Yapay Zeka Çeviri Modelini Sil (models/opus-en-tr-ct2 — {model_mb:.1f} MB)"
        )
        chk_model.setChecked(False)
        chk_model.setStyleSheet("color: #FACC15; font-weight: 600;")
        v_card.addWidget(chk_model)

        lbl_runtime_info = QLabel(
            f"• Taşınabilir Çalışma Ortamı (runtime/): {runtime_mb:.1f} MB  |  Konum: {app_dir}"
        )
        lbl_runtime_info.setWordWrap(True)
        lbl_runtime_info.setStyleSheet("color: #71717A; font-size: 8.2pt; padding-top: 4px;")
        v_card.addWidget(lbl_runtime_info)

        v_main.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_clean = QPushButton("Seçili Bileşenleri Temizle")
        btn_clean.setStyleSheet(
            "QPushButton { background-color: #18181B; border: 1px solid #D97706; color: #FBBF24; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #27272A; }"
        )

        btn_uninst = QPushButton("Tam Kaldırma Yardımcısını Aç (Uninstaller)")
        btn_uninst.setStyleSheet(
            "QPushButton { background-color: #DC2626; border: 1px solid #EF4444; color: #FFFFFF; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #B91C1C; }"
        )

        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(dlg.reject)

        def _on_clean_clicked() -> None:
            if not (chk_cache.isChecked() or chk_settings.isChecked() or chk_model.isChecked()):
                QMessageBox.information(dlg, "SubVision AI", "Lütfen temizlemek için en az bir bileşen seçin.")
                return

            cleaned_items: List[str] = []
            if chk_cache.isChecked():
                self.translator.clear_cache()
                self.list_history.clear()
                self._update_session_kpi()
                cleaned_items.append("RAM çeviri önbelleği ve geçmiş")

            if chk_settings.isChecked():
                for p in (CONFIG_PATH, CRASH_LOG_PATH, os.path.join(app_dir, "benchmark_results.json")):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                cleaned_items.append("Kullanıcı ayarları (user_settings.json)")

            if chk_model.isChecked():
                if self.worker and self.worker.running:
                    self.toggle_translation()
                self.translator.translator = None
                self.translator.source_sp = None
                self.translator.target_sp = None
                self.translator.is_ready = False
                import shutil

                shutil.rmtree(self.translator.model_dir, ignore_errors=True)
                self.btn_toggle.setEnabled(False)
                self.lbl_model_status.setText("●  Yapay zeka modeli silindi (Yeniden indirmek için uygulamayı başlatın)")
                cleaned_items.append("İndirilen yapay zeka çeviri modeli (~227 MB)")

            QMessageBox.information(
                dlg,
                "SubVision AI — Temizlendi",
                "Seçili bileşenler başarıyla temizlendi:\n• " + "\n• ".join(cleaned_items),
            )
            dlg.accept()

        def _on_uninstaller_clicked() -> None:
            uninst_candidates = [
                os.path.join(app_dir, "SubVisionAI-Uninstaller.exe"),
                os.path.join(app_dir, "SubVisionAI.exe"),
                os.path.join(app_dir, "unins000.exe"),
            ]
            target_exe = next((p for p in uninst_candidates if os.path.exists(p)), None)
            if not target_exe:
                QMessageBox.information(
                    dlg,
                    "SubVision AI",
                    "SubVisionAI-Uninstaller.exe bulunamadı.\nDerlemek için: python build_exe.py",
                )
                return

            ans = QMessageBox.question(
                dlg,
                "Tam Kaldırma Yardımcısı",
                "Kaldırma Yardımcısının (SubVisionAI-Uninstaller.exe) çalışma ortamı dosyalarını "
                "serbestçe silebilmesi için mevcut uygulama penceresi kapatılacak.\n\n"
                "Kaldırma Yardımcısını şimdi başlatmak istiyor musunuz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                import subprocess

                args = [target_exe]
                if not target_exe.lower().endswith("unins000.exe"):
                    args.append("--uninstall")
                subprocess.Popen(args, cwd=app_dir)
                dlg.accept()
                self.close()

        btn_clean.clicked.connect(_on_clean_clicked)
        btn_uninst.clicked.connect(_on_uninstaller_clicked)

        btn_row.addWidget(btn_clean)
        btn_row.addWidget(btn_uninst)
        btn_row.addWidget(btn_close)
        v_main.addLayout(btn_row)

        dlg.exec()

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
