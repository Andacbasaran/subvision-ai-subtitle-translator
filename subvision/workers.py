"""
SubVision AI — Asynchronous Background Workers & Latest-Frame-Wins Pipeline.
Extracted from main.py for modular architecture and isolated unit testing.
"""

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from subvision.hardware import HardwareProfile
from subvision.ocr_engine import SubtitleOCREngine
from subvision.window_tracker import (
    TargetWindowSpec,
    WindowInfo,
    get_foreground_window_info,
    is_target_foreground,
)


class ModelLoaderThread(QThread):
    """
    Arayüzü dondurmadan arka planda önce RapidOCR (ONNX) motorunu,
    ardından CTranslate2 çeviri modelini işlemciye uygun modda yükler.
    """

    progress = pyqtSignal(str, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, translator, ocr_engine: SubtitleOCREngine, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.ocr_engine = ocr_engine

    def run(self) -> None:
        try:
            self.progress.emit("Yapay zeka görüntü okuma motoru hazırlanıyor...", 10)
            self.ocr_engine.ensure_initialized()
            self.progress.emit("Çeviri motoru hazırlanıyor...", 22)
            self.translator.load(
                progress_callback=lambda msg, pct: self.progress.emit(
                    msg, max(22, int(22 + pct * 0.78))
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
        translator,
        hw_profile: HardwareProfile,
        parent=None,
    ):
        super().__init__(parent)
        self.ocr_engine = ocr_engine
        self.translator = translator
        self.hw_profile = hw_profile

    def run(self) -> None:
        local_tr = getattr(self.translator, "local", self.translator)
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
            with local_tr._lock:
                local_tr._cache.pop(s.lower(), None)
            _, ms, _ = local_tr.translate_with_metrics(s)
            nmt_times.append(ms)
        avg_nmt_ms = sum(nmt_times) / max(1, len(nmt_times))

        t_c = time.perf_counter()
        for _ in range(100):
            local_tr.translate_with_metrics(test_sentences[0])
        cache_ms = ((time.perf_counter() - t_c) * 1000.0) / 100.0

        report = {
            "cpu_name": self.hw_profile.short_cpu_label,
            "cores": f"{self.hw_profile.physical_cores}C/{self.hw_profile.logical_cores}T",
            "compute_type": local_tr.active_compute_type.upper(),
            "pixel_lock_ms": pixel_lock_ms,
            "avg_ocr_ms": avg_ocr_ms,
            "avg_nmt_ms": avg_nmt_ms,
            "cache_ms": cache_ms,
            "total_cold_ms": avg_ocr_ms + avg_nmt_ms,
            "total_cached_ms": avg_ocr_ms + cache_ms,
            "threads": local_tr.cpu_threads,
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
        self._pending: Optional[Tuple[int, str, float, int, Optional[dict]]] = None
        self._closed: bool = False
        self.dropped_count: int = 0

    @property
    def generation(self) -> int:
        with self._cond:
            return self._generation

    def submit(
        self,
        en_text: str,
        ocr_ms: float,
        orig_line_h: int = 0,
        layout: Optional[dict] = None,
    ) -> int:
        with self._cond:
            if self._pending is not None:
                self.dropped_count += 1
            self._generation += 1
            gen = self._generation
            self._pending = (gen, en_text, ocr_ms, orig_line_h, layout)
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

    def take_with_layout(
        self, timeout: float = 0.25
    ) -> Optional[Tuple[int, str, float, int, Optional[dict]]]:
        with self._cond:
            if self._pending is None and not self._closed:
                self._cond.wait(timeout=timeout)
            if self._closed or self._pending is None:
                return None
            item = self._pending
            self._pending = None
            return item

    def take(self, timeout: float = 0.25) -> Optional[Tuple[int, str, float, int]]:
        item = self.take_with_layout(timeout=timeout)
        if item is None:
            return None
        gen, en_text, ocr_ms, orig_line_h, _layout = item
        return (gen, en_text, ocr_ms, orig_line_h)

    def is_current(self, generation: int) -> bool:
        with self._cond:
            return (not self._closed) and (generation == self._generation)


class CaptureTranslateWorker(QThread):
    subtitle_updated = pyqtSignal(str, str, float, float, bool, int, object)
    subtitle_cleared = pyqtSignal()
    status_tick = pyqtSignal(str)
    target_focus_changed = pyqtSignal(bool)

    def __init__(
        self,
        ocr_engine: SubtitleOCREngine,
        translator,
        roi: Dict[str, int],
        scan_interval_sec: float = 0.0417,
        idle_scan_interval_sec: float = 0.0714,
        target_filter: Optional[TargetWindowSpec] = None,
        foreground_provider: Callable[[], Optional[WindowInfo]] = get_foreground_window_info,
        parent=None,
    ):
        super().__init__(parent)
        self.ocr_engine = ocr_engine
        self.translator = translator
        self.roi = dict(roi)
        self.scan_interval_sec = max(0.025, float(scan_interval_sec))
        self.idle_scan_interval_sec = max(self.scan_interval_sec, float(idle_scan_interval_sec))
        self.running = False
        self._slot = LatestTextSlot()
        self._nmt_thread: Optional[threading.Thread] = None
        self._filter_lock = threading.Lock()
        self._roi_lock = threading.Lock()
        self._target_filter: Optional[TargetWindowSpec] = target_filter
        self._filter_dirty: bool = True
        self._foreground_provider = foreground_provider

    def update_roi(self, new_roi: Dict[str, int]) -> None:
        with self._roi_lock:
            self.roi = dict(new_roi)

    def _get_roi_snapshot(self) -> Dict[str, int]:
        with self._roi_lock:
            return dict(self.roi)

    def update_timing(self, scan_interval_sec: float, idle_scan_interval_sec: float) -> None:
        self.scan_interval_sec = max(0.025, float(scan_interval_sec))
        self.idle_scan_interval_sec = max(self.scan_interval_sec, float(idle_scan_interval_sec))

    def set_target_filter(self, spec: Optional[TargetWindowSpec]) -> None:
        with self._filter_lock:
            self._target_filter = spec
            self._filter_dirty = True

    def _get_target_filter(self) -> Tuple[Optional[TargetWindowSpec], bool]:
        with self._filter_lock:
            dirty = self._filter_dirty
            self._filter_dirty = False
            return self._target_filter, dirty

    def _translation_loop(self) -> None:
        while self.running:
            item = self._slot.take_with_layout(timeout=0.25)
            if item is None:
                continue
            gen, en_text, ocr_ms, orig_line_h, layout = item
            if not self._slot.is_current(gen):
                continue
            try:
                tr_text, tr_ms, is_cached = self.translator.translate_with_metrics(en_text)
                if tr_text and self.running and self._slot.is_current(gen):
                    self.subtitle_updated.emit(
                        en_text, tr_text, ocr_ms, tr_ms, is_cached, orig_line_h, layout
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
        target_active = True
        last_focus_check_ts = 0.0

        with mss.mss() as sct:
            while self.running:
                loop_start = time.perf_counter()
                try:
                    target_spec, filter_dirty = self._get_target_filter()
                    now_mono = time.monotonic()
                    if target_spec and target_spec.is_active:
                        if filter_dirty or (now_mono - last_focus_check_ts) >= 0.10:
                            last_focus_check_ts = now_mono
                            fg = self._foreground_provider()
                            is_focused = is_target_foreground(target_spec, fg)
                            if is_focused != target_active:
                                target_active = is_focused
                                if not target_active:
                                    self._slot.invalidate()
                                    self.ocr_engine.reset_state()
                                    self.subtitle_cleared.emit()
                                    self.target_focus_changed.emit(False)
                                else:
                                    self.ocr_engine.reset_state()
                                    idle_streak_sec = 0.0
                                    self.target_focus_changed.emit(True)
                    elif not target_active:
                        target_active = True
                        self.ocr_engine.reset_state()
                        idle_streak_sec = 0.0
                        self.target_focus_changed.emit(True)

                    if not target_active:
                        time.sleep(0.12)
                        continue

                    roi_snap = self._get_roi_snapshot()
                    capture_box = {
                        "left": int(roi_snap["left"]),
                        "top": int(roi_snap["top"]),
                        "width": int(roi_snap["width"]),
                        "height": int(roi_snap["height"]),
                    }
                    status, en_text, ocr_ms = self.ocr_engine.capture_and_read(capture_box, sct)

                    if status == "EMPTY":
                        self._slot.invalidate()
                        self.subtitle_cleared.emit()
                        idle_streak_sec += self.scan_interval_sec
                    elif status == "NEW_TEXT" and en_text:
                        idle_streak_sec = 0.0
                        orig_line_h = self.ocr_engine.last_line_height_px
                        layout = self.ocr_engine.last_subtitle_layout
                        fast_hit = self.translator.try_fast_lookup(en_text)
                        if fast_hit is not None:
                            self._slot.invalidate()
                            tr_text, tr_ms, is_cached = fast_hit
                            self.subtitle_updated.emit(
                                en_text, tr_text, ocr_ms, tr_ms, is_cached, orig_line_h, layout
                            )
                        else:
                            self._slot.submit(en_text, ocr_ms, orig_line_h, layout=layout)
                    else:
                        idle_streak_sec += self.scan_interval_sec
                except Exception as exc:
                    self.status_tick.emit(f"Yakalama hatası: {exc}")

                elapsed = time.perf_counter() - loop_start
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
