"""
SubVision AI — Ultra Hızlı Bölgesel Ekran Yakalama (MSS) + Piksel Değişim Kilidi + RapidOCR (ONNX CPU) Modülü.
Oyunlar, Diziler, Filmler ve Canlı Yayınlardaki İngilizce altyazıları yakalamak için optimize edilmiştir.

Mimari & Hız Optimizasyonları:
1. Kontür ve Kutu Doğrulamalı Renk Maskesi (Outline & Box-Verified Subtitle Mask):
   Oyunlardaki parlak arka planları (gökyüzü, patlama, far) eler; yalnızca etrafında koyu kontür/gölge
   veya koyu altyazı bandı (Netflix, YouTube, Prime Video, VLC, Oyunlar) bulunan Beyaz, Sarı ve Turkuaz
   altyazı harflerini ayıklar.
2. Yatay Satır Projeksiyonu (Fast Line Projection):
   Ağır DBNet metin arama katmanını (~1200-1500 ms) atlayarak satırları 0.2 ms'de keser ve tek bir
   ONNX batch halinde doğrudan CRNN Recognizer katmanına gönderir (~20-35 ms).
3. Çoklu Algılama Modu (Oyun/Sinema Hızlı Filtre & Genel Ekran Tam Kare OCR):
   Hem kontürlü oyun/dizi altyazılarında hem de açık renk zeminli diyalog kutularında çalışır.
4. Anti-Flicker & Parlama Koruması:
   Sahne geçişlerinde ve patlama/flaş anlarında mevcut Türkçe altyazının titremesini önler.
"""

import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from glossary import clean_ocr_text, is_plausible_subtitle_text
from hardware import (
    RuntimeTuning,
    apply_thread_env_defaults,
    compute_runtime_tuning,
    detect_hardware_profile,
)

_KERNEL_DARK_NEIGHBOR = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
_KERNEL_HORIZ_CONNECT = cv2.getStructuringElement(cv2.MORPH_RECT, (14, 2))

# ONNX Runtime Dynamic Shape Re-Planning'i (~80 ms) tamamen sıfırlamak için sabit en/boy oranı kovaları
_BUCKET_RATIOS = (10, 16, 22)


class SubtitleOCREngine:
    def __init__(
        self,
        use_color_mask: bool = True,
        similarity_threshold: float = 0.85,
        ocr_mode: str = "fast_mask",
        tuning: Optional[RuntimeTuning] = None,
        lazy_init: bool = False,
    ):
        if tuning is None:
            hw = detect_hardware_profile(query_ct2=False)
            tuning = compute_runtime_tuning(hw)
        self.tuning = tuning
        apply_thread_env_defaults(tuning)

        self.cv_threads = tuning.cv_threads
        self.ocr_intra_threads = tuning.ocr_intra_threads
        self.ocr_inter_threads = tuning.ocr_inter_threads
        self.max_capture_width = tuning.max_capture_width
        self.det_limit_side_len = tuning.det_limit_side_len
        self.warmup_buckets = tuning.warmup_buckets
        self.warmup_double_line = tuning.warmup_double_line

        self._apply_cv_threads(self.cv_threads)

        self.ocr: Optional[RapidOCR] = None
        self.is_initialized = False
        self.use_color_mask = use_color_mask
        self.ocr_mode = ocr_mode if use_color_mask else "full_ocr"
        self.similarity_threshold = similarity_threshold

        self._prev_raw_thumb: Optional[np.ndarray] = None
        self._prev_thumb: Optional[np.ndarray] = None
        self._last_clean_text: str = ""
        self._empty_frames_count: int = 0
        self._last_bright_ratio: float = 0.0
        self._fade_wait_frames: int = 0
        self._pending_borderline_text: str = ""
        self._last_hybrid_dbnet_ts: float = 0.0

        # Auto-Fit ve dinamik sıkı hizalama (tight-hug) overlay için ölçülen orijinal altyazı metrikleri
        self.last_line_height_px: int = 0
        self.last_line_count: int = 0
        self.last_subtitle_layout: Optional[Dict] = None
        self._last_read_boxes: List[Tuple[int, int, int, int]] = []
        self._last_read_proc_shape: Tuple[int, int] = (0, 0)
        self._last_read_layout: Optional[Dict] = None

        if not lazy_init:
            self.ensure_initialized()

    @staticmethod
    def _apply_cv_threads(num_threads: int) -> None:
        # OpenCV'nin gereksiz CPU thread açıp oyun veya videoyu yavaşlatmasını engelle
        try:
            cv2.setNumThreads(max(1, int(num_threads)))
        except Exception:
            pass

    def apply_tuning(self, tuning: RuntimeTuning) -> None:
        """
        Performans profili değiştirildiğinde tarama çözünürlüğü ve OpenCV thread ayarını günceller.
        """
        self.tuning = tuning
        self.cv_threads = tuning.cv_threads
        self.max_capture_width = tuning.max_capture_width
        self.det_limit_side_len = tuning.det_limit_side_len
        self._apply_cv_threads(self.cv_threads)
        self.reset_state()

    def ensure_initialized(self) -> None:
        """
        RapidOCR (ONNX Runtime) motorunu işlemciye uygun thread limitleriyle yükler ve
        sabit en/boy oranı kovaları (Shape Buckets) için ısıtır.
        """
        if self.is_initialized and self.ocr is not None:
            return

        ocr_kwargs = {
            "use_cls": False,
            "det_limit_side_len": self.det_limit_side_len,
            "det_limit_type": "max",
            "intra_op_num_threads": self.ocr_intra_threads,
            "inter_op_num_threads": self.ocr_inter_threads,
        }
        try:
            self.ocr = RapidOCR(**ocr_kwargs)
        except Exception:
            # Farklı RapidOCR sürümleri için güvenli yedek başlatma
            self.ocr = RapidOCR(
                use_cls=False,
                det_limit_side_len=self.det_limit_side_len,
                det_limit_type="max",
            )

        # ONNX Runtime CRNN motorunu sabit en/boy oranı kovaları (Shape Buckets) için ısıt (Warm-up)
        # Böylece farklı uzunluktaki yeni altyazılarda ~80 ms'lik ONNX kernel re-planning gecikmesi sıfırlanır.
        try:
            for r in self.warmup_buckets:
                dummy = np.full((32, 32 * r, 3), 255, dtype=np.uint8)
                self.ocr.text_rec([dummy])
                if self.warmup_double_line:
                    self.ocr.text_rec([dummy, dummy])
        except Exception:
            pass

        self.is_initialized = True

    def set_mode(self, mode: str) -> None:
        """
        Algılama modunu değiştirir:
        - 'fast_mask': Oyun & Dizi/Film (Adaptif Kontür & Yerel Kontrast Filtresi - Ultra Hızlı, Önerilen)
        - 'hybrid': Akıllı Hibrit (Önce Hızlı Filtre, kenar yoğunluğu varsa kısıtlı DBNet yedeklemesi)
        - 'full_ocr': Genel Ekran & Video (Tam Kare OCR - Açık Zemin / Kontürsüz Metinler)
        """
        self.ocr_mode = mode
        self.use_color_mask = mode != "full_ocr"
        self.reset_state()

    def reset_state(self) -> None:
        self._prev_raw_thumb = None
        self._prev_thumb = None
        self._last_clean_text = ""
        self._empty_frames_count = 0
        self._last_bright_ratio = 0.0
        self._fade_wait_frames = 0
        self._pending_borderline_text = ""
        self._last_hybrid_dbnet_ts = 0.0
        self.last_line_height_px = 0
        self.last_line_count = 0
        self.last_subtitle_layout = None
        self._last_read_boxes = []
        self._last_read_proc_shape = (0, 0)
        self._last_read_layout = None

    @staticmethod
    def compute_subtitle_binary_mask(bgr_img: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Adaptif Yerel Kontrast ve Renkli Konuşmacı Destekli Altyazı Maskesi:
        - Beyaz (yarı saydam / 4K anti-aliased ince fontlar dahil), Sarı, Turkuaz altyazıları
        - Spider-Man 2 gibi modern oyunlardaki renkli konuşmacı adlarını (kırmızı, mavi, yeşil, turuncu)
        - Parlak gökyüzü üzerindeki yarı saydam koyu altyazı bantlarını yakalar.
        - Düz parlak gökyüzü, bulut ve düşük kontrastlı oyun arka planlarını reddeder.
        """
        b = bgr_img[:, :, 0]
        g = bgr_img[:, :, 1]
        r = bgr_img[:, :, 2]

        max_c = np.maximum(np.maximum(r, g), b)
        min_c = np.minimum(np.minimum(r, g), b)
        chroma = max_c - min_c

        # Hızlı tamsayı parlaklık (luma) + yerel minimum (9x9 komşuluktaki en koyu kontür/zemin)
        luma = ((r.astype(np.uint16) * 77 + g.astype(np.uint16) * 150 + b.astype(np.uint16) * 29) >> 8).astype(
            np.uint8
        )
        local_min = cv2.erode(luma, _KERNEL_DARK_NEIGHBOR)
        local_contrast = luma.astype(np.int16) - local_min.astype(np.int16)

        # 1. Beyaz / Açık Gri Altyazı (ince 4K fontlar ve %80 opaklıklı oyun altyazıları dahil)
        white_mask = (min_c > 152) & (chroma < 56)

        # 2. Sarı / Altın Sinema & Oyun Altyazısı
        yellow_mask = (r > 175) & (g > 145) & (b < 140)

        # 3. Turkuaz / Camgöbeği Altyazı
        cyan_mask = (b > 170) & (g > 165) & (r < 130)

        # 4. Renkli Konuşmacı İsimleri (örn. Spider-Man 2: Peter/Miles/MJ mavi, kırmızı, yeşil, turuncu)
        speaker_color_mask = (max_c > 178) & (chroma > 65) & (local_min < 120) & (local_contrast >= 60)

        # Standart altyazı renkleri için koyu kontür / yarı saydam şerit + yerel kontrast doğrulaması
        standard_bright = white_mask | yellow_mask | cyan_mask
        has_dark_outline = (local_min < 145) & (local_contrast >= 48)

        combined_mask = (standard_bright & has_dark_outline) | speaker_color_mask
        mask_u8 = (combined_mask.astype(np.uint8)) * 255
        bright_ratio = float(np.mean(combined_mask))
        return mask_u8, bright_ratio

    @staticmethod
    def mask_to_ocr_bgr(mask_u8: np.ndarray) -> np.ndarray:
        """OCR için en yüksek kontrastlı format: Beyaz zemin (255) üzerine siyah harfler (0)."""
        ocr_ready = 255 - mask_u8
        return cv2.cvtColor(ocr_ready, cv2.COLOR_GRAY2BGR)

    @classmethod
    def apply_subtitle_color_mask(cls, bgr_img: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        Oyunlar, diziler ve medya oynatıcılardaki altyazı piksellerini yerel kontrast doğrulamasıyla ayıklar.
        Dönüş: (ocr_ready_bgr, binary_mask_u8, parlak_piksel_orani)
        """
        mask_u8, bright_ratio = cls.compute_subtitle_binary_mask(bgr_img)
        ocr_ready_bgr = cls.mask_to_ocr_bgr(mask_u8)
        return ocr_ready_bgr, mask_u8, bright_ratio

    @staticmethod
    def _filter_horizontal_runs(xs: np.ndarray, line_h: int) -> Tuple[int, int]:
        """
        Satırdaki aktif X sütunlarını yatay kümelere ayırır ve ana metinden çok uzakta kalan
        küçük izole HUD/parazit noktalarını (outlier) atarak sıkı (tight) yatay sınırları döndürür.
        """
        if len(xs) == 0:
            return 0, 0
        split_gap = max(40, int(line_h * 3.5))
        diffs = np.diff(xs)
        split_idx = np.where(diffs > split_gap)[0] + 1
        clusters = np.split(xs, split_idx)
        if len(clusters) == 1:
            return int(xs[0]), int(xs[-1])

        spans = [(int(c[0]), int(c[-1]), len(c)) for c in clusters if len(c) > 0]
        main_idx = max(range(len(spans)), key=lambda i: (spans[i][1] - spans[i][0], spans[i][2]))
        main_x1, main_x2, _ = spans[main_idx]

        min_island_w = max(18, int(line_h * 1.4))
        max_island_gap = max(48, int(line_h * 4.0))
        kept: List[Tuple[int, int]] = []
        for idx, (cx1, cx2, _cnt) in enumerate(spans):
            if idx == main_idx:
                kept.append((cx1, cx2))
                continue
            cw = cx2 - cx1
            dist_to_main = min(abs(cx2 - main_x1), abs(cx1 - main_x2))
            if cw >= min_island_w or dist_to_main <= max_island_gap:
                kept.append((cx1, cx2))

        return min(c[0] for c in kept), max(c[1] for c in kept)

    @staticmethod
    def _group_dbnet_boxes_into_lines(
        boxes: List[Tuple[int, int, int, int]]
    ) -> List[Tuple[int, int, int, int]]:
        """
        DBNet kelime/parça kutularını dikey örtüşmeye göre görsel satırlara birleştirir
        ve yukarıdan aşağıya sıralı sıkı satır kutuları döndürür.
        """
        if not boxes:
            return []
        ordered = sorted(boxes, key=lambda b: ((b[1] + b[3]) * 0.5, b[0]))
        lines: List[List[int]] = []
        for x1, y1, x2, y2 in ordered:
            bh = max(1, y2 - y1)
            ymid = (y1 + y2) * 0.5
            merged = False
            for line in lines:
                ly1, ly2 = line[1], line[3]
                lh = max(1, ly2 - ly1)
                lmid = (ly1 + ly2) * 0.5
                overlap = min(y2, ly2) - max(y1, ly1)
                min_h = min(bh, lh)
                if overlap >= 0.45 * min_h or abs(ymid - lmid) <= 0.55 * min_h:
                    line[0] = min(line[0], x1)
                    line[1] = min(line[1], y1)
                    line[2] = max(line[2], x2)
                    line[3] = max(line[3], y2)
                    merged = True
                    break
            if not merged:
                lines.append([x1, y1, x2, y2])
        lines.sort(key=lambda b: (b[1], b[0]))
        return [(b[0], b[1], b[2], b[3]) for b in lines]

    @staticmethod
    def _build_normalized_layout(
        line_boxes: List[Tuple[int, int, int, int]],
        proc_w: int,
        proc_h: int,
        measured_h: int = 0,
        roi: Optional[Dict[str, int]] = None,
        safe_roi: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict]:
        """
        Algılanan satır kutularını DPI ve yeniden boyutlandırmadan bağımsız [0.0, 1.0] ROI
        koordinatlarına dönüştürür.
        """
        if not line_boxes or proc_w <= 0 or proc_h <= 0:
            return None

        roi_w = float(roi["width"]) if (roi and roi.get("width", 0) > 0) else float(proc_w)
        roi_h = float(roi["height"]) if (roi and roi.get("height", 0) > 0) else float(proc_h)
        off_x = float(safe_roi["left"] - roi["left"]) if (roi and safe_roi) else 0.0
        off_y = float(safe_roi["top"] - roi["top"]) if (roi and safe_roi) else 0.0
        span_w = float(safe_roi["width"]) if (safe_roi and safe_roi.get("width", 0) > 0) else roi_w
        span_h = float(safe_roi["height"]) if (safe_roi and safe_roi.get("height", 0) > 0) else roi_h

        def _norm_x(px: float) -> float:
            u = (off_x + (px / float(proc_w)) * span_w) / max(1.0, roi_w)
            return max(0.0, min(1.0, round(u, 5)))

        def _norm_y(py: float) -> float:
            v = (off_y + (py / float(proc_h)) * span_h) / max(1.0, roi_h)
            return max(0.0, min(1.0, round(v, 5)))

        norm_lines: List[Tuple[float, float, float, float]] = []
        norm_heights: List[float] = []
        for x1, y1, x2, y2 in line_boxes:
            u1, v1 = _norm_x(x1), _norm_y(y1)
            u2, v2 = _norm_x(x2), _norm_y(y2)
            if u2 > u1 and v2 > v1:
                norm_lines.append((u1, v1, u2, v2))
                norm_heights.append(v2 - v1)

        if not norm_lines:
            return None

        u_min = min(b[0] for b in norm_lines)
        v_min = min(b[1] for b in norm_lines)
        u_max = max(b[2] for b in norm_lines)
        v_max = max(b[3] for b in norm_lines)

        if measured_h > 0:
            line_h_norm = max(0.01, min(1.0, ((float(measured_h) / float(proc_h)) * span_h) / max(1.0, roi_h)))
        else:
            norm_heights.sort()
            line_h_norm = norm_heights[len(norm_heights) // 2]

        return {
            "bbox": (u_min, v_min, u_max, v_max),
            "lines": norm_lines,
            "line_h_norm": round(line_h_norm, 5),
            "line_count": len(norm_lines),
        }

    @staticmethod
    def _layout_changed_significantly(
        prev_layout: Optional[Dict], new_layout: Optional[Dict]
    ) -> bool:
        """Benzer metinde 2. satırın eklenmesi veya kutunun büyümesi halinde overlay güncellemesi sağlar."""
        if not new_layout or not new_layout.get("bbox"):
            return False
        if not prev_layout or not prev_layout.get("bbox"):
            return True
        pu1, pv1, pu2, pv2 = prev_layout["bbox"]
        nu1, nv1, nu2, nv2 = new_layout["bbox"]
        pw = max(1e-4, pu2 - pu1)
        ph = max(1e-4, pv2 - pv1)
        nw = max(1e-4, nu2 - nu1)
        nh = max(1e-4, nv2 - nv1)
        if nw > pw * 1.12 or nh > ph * 1.12:
            return True
        if abs(nu1 - pu1) > 0.06 or abs(nu2 - pu2) > 0.06 or abs(nv1 - pv1) > 0.08 or abs(nv2 - pv2) > 0.08:
            return True
        return False

    @classmethod
    def extract_fast_line_crops_with_boxes(
        cls, ocr_ready_bgr: np.ndarray, mask_u8: np.ndarray
    ) -> Tuple[List[np.ndarray], List[Tuple[int, int, int, int]], int, int]:
        """
        0.2 ms'de ikili (binary) altyazı maskesinden 1-4 satırlık sıkı (tight) altyazı şeritlerini
        ve her satırın tam (x1, y1, x2, y2) sınır kutusunu çıkarır.
        Dönüş: (line_crops, line_boxes_px, median_line_height_px, line_count)
        """
        h, w = mask_u8.shape[:2]
        connected = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, _KERNEL_HORIZ_CONNECT)

        row_counts = np.sum(connected > 0, axis=1)
        # Geniş ROI'lerde tek kelimelik kısa replikleri ("No!", "Hey!") kaybetmemek için %0.5 taban
        min_pixels_in_row = max(5, int(w * 0.005))
        active_rows = row_counts >= min_pixels_in_row

        lines_y: List[Tuple[int, int]] = []
        in_line = False
        y_start = 0
        gap_count = 0

        for y in range(h):
            if active_rows[y]:
                if not in_line:
                    y_start = y
                    in_line = True
                gap_count = 0
            else:
                if in_line:
                    gap_count += 1
                    if gap_count > 2:
                        y_end = y - gap_count + 1
                        if (y_end - y_start) >= 8:
                            lines_y.append((y_start, y_end))
                        in_line = False
                        gap_count = 0

        if in_line:
            y_end = h
            if (y_end - y_start) >= 8:
                lines_y.append((y_start, y_end))

        max_valid_line_h = max(64, int(h * 0.80))
        crops: List[np.ndarray] = []
        boxes: List[Tuple[int, int, int, int]] = []
        valid_heights: List[int] = []

        for y1, y2 in lines_y[:4]:
            line_h = y2 - y1
            if line_h > max_valid_line_h:
                continue

            band = connected[y1:y2, :]
            col_counts = np.sum(band > 0, axis=0)
            xs = np.where(col_counts >= 2)[0]
            if len(xs) < 4:
                continue

            x1, x2 = cls._filter_horizontal_runs(xs, line_h)
            line_w = x2 - x1
            if line_w < 10:
                continue

            # Geometrik Mürekkep Yoğunluğu (Ink-Ratio) Kontrolü:
            # Gerçek metin satırları %3.5 - %66 arası dolu olur; solid beyaz far/kutu (>%68) veya
            # dağınık tek piksellik parazitler (<%3.5) OCR'a hiç gönderilmeden elenir.
            raw_ink_ratio = float(np.mean(mask_u8[y1:y2, x1 : x2 + 1] > 0))
            if raw_ink_ratio < 0.035 or raw_ink_ratio > 0.68:
                continue

            cy1 = max(0, y1 - 5)
            cy2 = min(h, y2 + 5)
            cx1 = max(0, x1 - 8)
            cx2 = min(w, x2 + 8)
            raw_crop = ocr_ready_bgr[cy1:cy2, cx1:cx2]

            # Sabit En/Boy Oranı Kovasına (10x, 16x, 22x) Sağdan Beyaz Dolgu (White Padding)
            ch, cw = raw_crop.shape[:2]
            if ch > 0:
                target_ratio = 10 if cw <= ch * 10 else (16 if cw <= ch * 16 else 22)
                target_w = ch * target_ratio
                if cw < target_w:
                    raw_crop = cv2.copyMakeBorder(
                        raw_crop,
                        0,
                        0,
                        0,
                        target_w - cw,
                        cv2.BORDER_CONSTANT,
                        value=(255, 255, 255),
                    )
            crops.append(raw_crop)
            boxes.append((x1, y1, x2, y2))
            valid_heights.append(line_h)

        median_h = sorted(valid_heights)[len(valid_heights) // 2] if valid_heights else 0
        return crops, boxes, median_h, len(crops)

    @classmethod
    def extract_fast_line_crops_with_metrics(
        cls, ocr_ready_bgr: np.ndarray, mask_u8: np.ndarray
    ) -> Tuple[List[np.ndarray], int, int]:
        """Geriye dönük uyumlu yardımcı: (line_crops, median_line_height_px, line_count) döndürür."""
        crops, _, median_h, line_count = cls.extract_fast_line_crops_with_boxes(
            ocr_ready_bgr, mask_u8
        )
        return crops, median_h, line_count

    @classmethod
    def extract_fast_line_crops(
        cls, ocr_ready_bgr: np.ndarray, mask_u8: np.ndarray
    ) -> List[np.ndarray]:
        """Geriye dönük uyumlu yardımcı: yalnızca satır kırpmalarını döndürür."""
        crops, _, _ = cls.extract_fast_line_crops_with_metrics(ocr_ready_bgr, mask_u8)
        return crops

    @staticmethod
    def _has_text_like_edges(frame_bgr: np.ndarray) -> bool:
        """
        Hibrit modda boş/hareketli oyun sahnelerinde gereksiz 200-600 ms DBNet çağrısını
        önlemek için hızlı yatay dikey-kenar (Sobel X) metin yoğunluğu kontrolü yapar.
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (240, max(16, int(gray.shape[0] * (240.0 / max(1, gray.shape[1]))))))
        grad_x = cv2.Sobel(small, cv2.CV_16S, 1, 0, ksize=3)
        abs_gx = np.abs(grad_x)
        edge_ratio = float(np.mean(abs_gx > 90))
        return 0.020 <= edge_ratio <= 0.42

    def _has_raw_frame_changed(self, frame_bgr: np.ndarray) -> bool:
        """
        1. Aşama Ultra Hafif Ham Kare Kilidi (~0.04 ms):
        Duraklatılmış video, menü veya sabit sahnelerde ağır renk maskesi ve
        morfoloji (dilate) işlemlerini tamamen atlayarak düşük güçlü işlemcileri rahatlatır.
        """
        thumb = cv2.resize(frame_bgr, (64, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
        if self._prev_raw_thumb is None:
            self._prev_raw_thumb = thumb
            return True

        diff = float(np.mean(np.abs(thumb - self._prev_raw_thumb))) / 255.0
        if diff < 0.0020:
            return False

        self._prev_raw_thumb = thumb
        return True

    def _has_frame_changed(self, gray_or_mask: np.ndarray) -> bool:
        thumb = cv2.resize(gray_or_mask, (64, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
        if self._prev_thumb is None:
            self._prev_thumb = thumb
            return True

        diff = float(np.mean(np.abs(thumb - self._prev_thumb))) / 255.0
        if diff < 0.0045:
            return False

        self._prev_thumb = thumb
        return True

    def is_similar_to_last(self, new_text: str) -> bool:
        if not self._last_clean_text or not new_text:
            return False
        a = new_text.lower()
        b = self._last_clean_text.lower()
        if a == b:
            return True
        ratio = SequenceMatcher(None, a, b).ratio()
        return ratio >= self.similarity_threshold

    def _read_image_detailed(
        self,
        frame_bgr: np.ndarray,
        precomputed_mask: Optional[Tuple[np.ndarray, np.ndarray]] = None,
        allow_hybrid_fallback: bool = True,
    ) -> Tuple[str, float, float, int, int]:
        """
        Görüntüyü okuyup (temiz_metin, sure_ms, ortalama_guven, satir_yuksekligi_px, satir_sayisi) döner.
        """
        self.ensure_initialized()
        assert self.ocr is not None

        t0 = time.perf_counter()
        proc_h, proc_w = frame_bgr.shape[:2]
        valid_lines: List[str] = []
        accepted_boxes: List[Tuple[int, int, int, int]] = []
        scores: List[float] = []
        measured_h = 0
        measured_lines = 0

        if self.use_color_mask:
            if precomputed_mask is not None:
                ocr_ready_bgr, mask_u8 = precomputed_mask
            else:
                ocr_ready_bgr, mask_u8, _ = self.apply_subtitle_color_mask(frame_bgr)
            line_crops, crop_boxes, measured_h, measured_lines = (
                self.extract_fast_line_crops_with_boxes(ocr_ready_bgr, mask_u8)
            )

            if line_crops:
                rec_res, _ = self.ocr.text_rec(line_crops)
                if rec_res:
                    accepted_heights: List[int] = []
                    for idx, (text, score) in enumerate(rec_res):
                        t_clean = text.strip()
                        sc = float(score)
                        # Kısa 1-4 harfli okumalarda hayalet paraziti önlemek için daha sıkı güven eşiği
                        min_req = 0.72 if len(t_clean) <= 4 else 0.60
                        if sc >= min_req and t_clean:
                            valid_lines.append(t_clean)
                            scores.append(sc)
                            if idx < len(crop_boxes):
                                bx = crop_boxes[idx]
                                accepted_boxes.append(bx)
                                accepted_heights.append(max(1, bx[3] - bx[1]))
                    if accepted_heights:
                        measured_h = sorted(accepted_heights)[len(accepted_heights) // 2]
                        measured_lines = len(accepted_boxes)

            # Hibrit modda hızlı filtre metin bulamazsa YALNIZCA cooldown + kenar yoğunluğu uygunsa DBNet çalıştır
            if not valid_lines and self.ocr_mode == "hybrid" and allow_hybrid_fallback:
                now = time.perf_counter()
                if (now - self._last_hybrid_dbnet_ts) >= 0.40 and self._has_text_like_edges(
                    frame_bgr
                ):
                    self._last_hybrid_dbnet_ts = now
                    res, _ = self.ocr(frame_bgr)
                    if res:
                        sorted_boxes = sorted(res, key=lambda item: (item[0][0][1], item[0][0][0]))
                        box_heights: List[int] = []
                        raw_db_boxes: List[Tuple[int, int, int, int]] = []
                        for box, text, score in sorted_boxes:
                            t_clean = text.strip()
                            sc = float(score)
                            min_req = 0.74 if len(t_clean) <= 4 else 0.64
                            if sc >= min_req and t_clean:
                                valid_lines.append(t_clean)
                                scores.append(sc)
                                try:
                                    xs = [int(round(pt[0])) for pt in box]
                                    ys = [int(round(pt[1])) for pt in box]
                                    x1, x2 = max(0, min(xs)), min(proc_w, max(xs))
                                    y1, y2 = max(0, min(ys)), min(proc_h, max(ys))
                                    if x2 > x1 and y2 > y1:
                                        raw_db_boxes.append((x1, y1, x2, y2))
                                        box_heights.append(y2 - y1)
                                except Exception:
                                    pass
                        accepted_boxes = self._group_dbnet_boxes_into_lines(raw_db_boxes)
                        if box_heights:
                            measured_h = sorted(box_heights)[len(box_heights) // 2]
                            measured_lines = max(1, len(accepted_boxes) or len(valid_lines))
        else:
            res, _ = self.ocr(frame_bgr)
            if res:
                sorted_boxes = sorted(res, key=lambda item: (item[0][0][1], item[0][0][0]))
                box_heights = []
                raw_db_boxes = []
                for box, text, score in sorted_boxes:
                    t_clean = text.strip()
                    sc = float(score)
                    min_req = 0.72 if len(t_clean) <= 4 else 0.60
                    if sc >= min_req and t_clean:
                        valid_lines.append(t_clean)
                        scores.append(sc)
                        try:
                            xs = [int(round(pt[0])) for pt in box]
                            ys = [int(round(pt[1])) for pt in box]
                            x1, x2 = max(0, min(xs)), min(proc_w, max(xs))
                            y1, y2 = max(0, min(ys)), min(proc_h, max(ys))
                            if x2 > x1 and y2 > y1:
                                raw_db_boxes.append((x1, y1, x2, y2))
                                box_heights.append(y2 - y1)
                        except Exception:
                            pass
                accepted_boxes = self._group_dbnet_boxes_into_lines(raw_db_boxes)
                if box_heights:
                    measured_h = sorted(box_heights)[len(box_heights) // 2]
                    measured_lines = max(1, len(accepted_boxes) or len(valid_lines))

        raw_joined = " ".join(valid_lines)
        cleaned = clean_ocr_text(raw_joined)
        avg_conf = (sum(scores) / len(scores)) if scores else 0.0

        if cleaned and not is_plausible_subtitle_text(cleaned, avg_confidence=avg_conf):
            cleaned = ""
            avg_conf = 0.0

        if cleaned and accepted_boxes:
            self._last_read_boxes = accepted_boxes
            self._last_read_proc_shape = (proc_w, proc_h)
            self._last_read_layout = self._build_normalized_layout(
                accepted_boxes, proc_w, proc_h, measured_h=measured_h
            )
        else:
            self._last_read_boxes = []
            self._last_read_proc_shape = (proc_w, proc_h)
            self._last_read_layout = None

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return cleaned, elapsed_ms, avg_conf, measured_h, measured_lines

    def read_image_fast(
        self,
        frame_bgr: np.ndarray,
        precomputed_mask: Optional[Tuple[np.ndarray, np.ndarray]] = None,
    ) -> Tuple[str, float]:
        cleaned, elapsed_ms, _, measured_h, measured_lines = self._read_image_detailed(
            frame_bgr, precomputed_mask=precomputed_mask
        )
        if cleaned:
            self.last_line_height_px = measured_h
            self.last_line_count = measured_lines
            self.last_subtitle_layout = self._last_read_layout
        else:
            self.last_subtitle_layout = None
        return cleaned, elapsed_ms

    @staticmethod
    def _clamp_roi(roi: Dict[str, int], sct: mss.base.MSSBase) -> Dict[str, int]:
        """
        Çözünürlük değişimi veya çoklu monitör geçişlerinde ROI koordinatlarının
        ekran dışına taşarak hata vermesini engeller.
        """
        vbox = sct.monitors[0]  # Tüm sanal ekran sınırları
        v_left = vbox["left"]
        v_top = vbox["top"]
        v_right = v_left + vbox["width"]
        v_bottom = v_top + vbox["height"]

        left = max(v_left, min(int(roi["left"]), v_right - 40))
        top = max(v_top, min(int(roi["top"]), v_bottom - 20))
        width = max(40, min(int(roi["width"]), v_right - left))
        height = max(20, min(int(roi["height"]), v_bottom - top))
        return {"left": left, "top": top, "width": width, "height": height}

    def capture_and_read(
        self, roi: Dict[str, int], sct: mss.base.MSSBase
    ) -> Tuple[str, str, float]:
        """
        Seçili ROI alanını yakalar ve değişiklik varsa OCR çalıştırır.
        Dönüş: (status, english_text, ocr_ms)
        """
        self.ensure_initialized()
        t0 = time.perf_counter()

        safe_roi = self._clamp_roi(roi, sct)
        sct_img = sct.grab(safe_roi)
        frame_bgra = np.asarray(sct_img)
        frame_bgr = frame_bgra[:, :, :3]

        # 1. Aşama: Ham ekran karesi hiç değişmediyse maskeleme ve morfoloji işlemlerini tamamen atla
        if not self._has_raw_frame_changed(frame_bgr):
            elapsed = (time.perf_counter() - t0) * 1000.0
            return "UNCHANGED", self._last_clean_text, elapsed

        orig_h, orig_w = frame_bgr.shape[:2]
        resize_scale = 1.0
        if orig_w > self.max_capture_width:
            resize_scale = float(self.max_capture_width) / orig_w
            frame_bgr = cv2.resize(
                frame_bgr,
                (self.max_capture_width, max(24, int(orig_h * resize_scale))),
                interpolation=cv2.INTER_AREA,
            )

        mask_u8_cached: Optional[np.ndarray] = None
        if self.use_color_mask:
            mask_u8, bright_ratio = self.compute_subtitle_binary_mask(frame_bgr)
            mask_u8_cached = mask_u8
            # Ekran parlaması / flaş durumunda mevcut altyazıyı koru
            if bright_ratio > 0.55:
                self._last_bright_ratio = bright_ratio
                elapsed = (time.perf_counter() - t0) * 1000.0
                return "UNCHANGED", self._last_clean_text, elapsed

            # Ekranda hiç parlak altyazı harfi kalmadıysa (4 kare sonra temizle)
            if bright_ratio < 0.0008 and self.ocr_mode == "fast_mask":
                self._last_bright_ratio = bright_ratio
                self._fade_wait_frames = 0
                self._pending_borderline_text = ""
                self._empty_frames_count += 1
                if self._empty_frames_count >= 4:
                    self._last_clean_text = ""
                    self._prev_thumb = None
                    self.last_subtitle_layout = None
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    return "EMPTY", "", elapsed
                elapsed = (time.perf_counter() - t0) * 1000.0
                return "UNCHANGED", self._last_clean_text, elapsed

            # Fade-In Stabilizasyon Kilidi:
            # Altyazı boş sahneden aniden belirirken (fade-in 1. karesi) 1 kare (~30ms) oturmasını bekle;
            # böylece silik/yarım harfleri okuyup 2 kez NMT çalıştırma maliyeti sıfırlanır.
            if (
                self._last_bright_ratio < 0.0010
                and bright_ratio >= 0.0015
                and self._fade_wait_frames == 0
            ):
                self._last_bright_ratio = bright_ratio
                self._fade_wait_frames = 1
                elapsed = (time.perf_counter() - t0) * 1000.0
                return "UNCHANGED", self._last_clean_text, elapsed

            self._last_bright_ratio = bright_ratio
            self._fade_wait_frames = 0

            check_plane = (
                mask_u8
                if (self.ocr_mode == "fast_mask" or bright_ratio >= 0.0008)
                else cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            )
        else:
            check_plane = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        if not self._has_frame_changed(check_plane):
            elapsed = (time.perf_counter() - t0) * 1000.0
            return "UNCHANGED", self._last_clean_text, elapsed

        precomputed: Optional[Tuple[np.ndarray, np.ndarray]] = None
        if mask_u8_cached is not None:
            precomputed = (self.mask_to_ocr_bgr(mask_u8_cached), mask_u8_cached)

        cleaned, _, avg_conf, measured_h, measured_lines = self._read_image_detailed(
            frame_bgr, precomputed_mask=precomputed
        )
        elapsed = (time.perf_counter() - t0) * 1000.0

        if not cleaned:
            self._pending_borderline_text = ""
            self._empty_frames_count += 1
            if self._empty_frames_count >= 4:
                self._last_clean_text = ""
                self.last_subtitle_layout = None
                return "EMPTY", "", elapsed
            return "UNCHANGED", self._last_clean_text, elapsed

        self._empty_frames_count = 0

        proc_w, proc_h = self._last_read_proc_shape
        new_layout = self._build_normalized_layout(
            self._last_read_boxes,
            proc_w,
            proc_h,
            measured_h=measured_h,
            roi=roi,
            safe_roi=safe_roi,
        )

        if self.is_similar_to_last(cleaned):
            self._pending_borderline_text = ""
            if self._layout_changed_significantly(self.last_subtitle_layout, new_layout):
                if measured_h > 0 and resize_scale > 0:
                    self.last_line_height_px = int(round(measured_h / resize_scale))
                    self.last_line_count = max(1, measured_lines)
                self.last_subtitle_layout = new_layout
                return "NEW_TEXT", self._last_clean_text, elapsed
            return "UNCHANGED", self._last_clean_text, elapsed

        # Sınır güvenli okumalarda (0.58 - 0.78) tek karelik hayalet paraziti önlemek için 2 kare onayı
        if avg_conf < 0.78:
            if self._pending_borderline_text and (
                SequenceMatcher(None, cleaned.lower(), self._pending_borderline_text.lower()).ratio()
                >= 0.80
            ):
                self._pending_borderline_text = ""
            else:
                self._pending_borderline_text = cleaned
                # Sonraki karede tekrar kontrol edilebilmesi için kare kilidini gevşet
                self._prev_raw_thumb = None
                self._prev_thumb = None
                return "UNCHANGED", self._last_clean_text, elapsed
        else:
            self._pending_borderline_text = ""

        # Ölçülen satır yüksekliğini orijinal yakalama piksel ölçeğine geri çevir
        if measured_h > 0 and resize_scale > 0:
            self.last_line_height_px = int(round(measured_h / resize_scale))
            self.last_line_count = max(1, measured_lines)

        self.last_subtitle_layout = new_layout
        self._last_clean_text = cleaned
        return "NEW_TEXT", cleaned, elapsed
