"""
SubVision AI — PyQt6 Şeffaf Dinamik Altyazı Katmanı (Click-Through Tight-Hugging Overlay)
ve Çoklu Monitör / 4K DPI Uyumlu Alan Seçici (ROI Selector).

Windows WDA_EXCLUDEFROMCAPTURE (0x11) özelliği sayesinde Türkçe altyazı kutusu,
orijinal İngilizce altyazının tam üstünü sıkıca (tight-fit) kapatsa bile ekran yakalayıcı (MSS)
tarafından görülmez. Oyunlar, Diziler, Filmler ve Yayınlar ile %100 uyumludur.
"""

import ctypes
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextLayout,
    QTextOption,
)
from PyQt6.QtWidgets import QWidget

from subvision.hardware import get_app_base_dir, get_ui_font_family, get_windows_build

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _get_win32_physical_cursor_pos() -> Optional[Tuple[int, int]]:
    """Windows PerMonitorV2 altında fiziksel sanal masaüstü imleç koordinatlarını döndürür."""
    if sys.platform != "win32":
        return None
    try:
        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = _POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
    except Exception:
        return None
    return None


def _event_local_point(event) -> QPoint:
    """PyQt6 event.position().toPoint() (ve eski uyumluluk için event.pos()) güvenli okuma."""
    try:
        return event.position().toPoint()
    except Exception:
        return event.pos()


def _load_brand_logo_pixmap(size: int = 32) -> Optional[QPixmap]:
    search_roots = [get_app_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    for root in search_roots:
        for fname in ("app_icon.png", "app_icon.ico"):
            p = os.path.join(root, "assets", fname)
            if os.path.exists(p):
                src = QPixmap(p)
                if not src.isNull():
                    px_size = max(16, int(size) * 2)
                    scaled = src.scaled(
                        px_size,
                        px_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    scaled.setDevicePixelRatio(2.0)
                    return scaled
    return None


def _configure_macos_overlay_window(widget: QWidget) -> None:
    """
    macOS (Cocoa) üzerinde altyazı overlay penceresinin:
    - Başka bir uygulamaya (tarayıcı/oyun/VLC) geçildiğinde gizlenmemesini (hidesOnDeactivate=NO)
    - Tıklamaları tamamen arkaya geçirmesini (ignoresMouseEvents=YES)
    - Tam ekran video ve diğer pencerelerin üstünde kalmasını (NSStatusWindowLevel + FullScreenAuxiliary)
    sağlar.
    """
    if sys.platform != "darwin":
        return
    try:
        if QGuiApplication.platformName() != "cocoa":
            return
        import ctypes.util

        objc_path = ctypes.util.find_library("objc")
        if not objc_path:
            return
        objc = ctypes.cdll.LoadLibrary(objc_path)
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p

        msg_id = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
        )
        msg_void_bool = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool),
        )
        msg_void_long = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long),
        )
        msg_void_ulong = ctypes.cast(
            objc.objc_msgSend,
            ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong),
        )

        ns_view = int(widget.winId())
        if not ns_view:
            return
        ns_win = msg_id(ns_view, objc.sel_registerName(b"window"))
        if not ns_win:
            return

        msg_void_bool(ns_win, objc.sel_registerName(b"setHidesOnDeactivate:"), False)
        msg_void_bool(ns_win, objc.sel_registerName(b"setIgnoresMouseEvents:"), True)
        msg_void_bool(ns_win, objc.sel_registerName(b"setHasShadow:"), False)
        # NSStatusWindowLevel (25): normal pencerelerin ve tam ekran oynatıcıların üstünde
        msg_void_long(ns_win, objc.sel_registerName(b"setLevel:"), 25)
        # CanJoinAllSpaces (1) | FullScreenAuxiliary (256)
        msg_void_ulong(ns_win, objc.sel_registerName(b"setCollectionBehavior:"), 1 | 256)
    except Exception:
        pass


def set_window_exclude_from_capture(widget: QWidget, exclude: bool = True) -> bool:
    """
    Windows 10 (2004 / Build 19041+) / Windows 11 API:
    Pencereyi kullanıcının gözüne görünür tutar ancak ekran yakalama (MSS/OCR) için
    %100 görünmez yapar. Böylece Türkçe altyazı, İngilizce altyazının tam üzerine
    yerleştirilse bile OCR kendi yazdığı Türkçe metni okumaz.
    Eski Windows sürümlerinde, Linux veya macOS'ta desteklenmiyorsa False döner.
    """
    if sys.platform == "win32":
        if exclude and get_windows_build() < 19041:
            return False
        try:
            hwnd = int(widget.winId())
            flag = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
            res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, flag)
            return bool(res)
        except Exception:
            return False
    return False


class ROISelectorOverlay(QWidget):
    """
    Fare ile ekranda oyun, dizi, film veya video oynatıcının İngilizce altyazısının
    çıktığı alanı (ROI) seçme ekranı. Çoklu monitör ve 4K yüksek DPI (%125-%200) uyumludur.
    """

    def __init__(
        self,
        on_selected: Callable[[Dict[str, int]], None],
        on_cancelled: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self.on_selected = on_selected
        self.on_cancelled = on_cancelled
        self.start_pos: Optional[QPoint] = None
        self.end_pos: Optional[QPoint] = None
        self._phys_start: Optional[Tuple[int, int]] = None
        self._phys_end: Optional[Tuple[int, int]] = None
        self.is_selecting = False
        self._active_screen = QGuiApplication.primaryScreen()
        self._logo_pix = _load_brand_logo_pixmap(34)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def show_selector(self) -> None:
        self.start_pos = None
        self.end_pos = None
        self._phys_start = None
        self._phys_end = None
        self.is_selecting = False

        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        self._active_screen = screen
        if screen:
            self.setGeometry(screen.geometry())

        self.show()
        self.activateWindow()
        self.raise_()

    def _cancel_selection(self) -> None:
        self.is_selecting = False
        self.start_pos = None
        self.end_pos = None
        self._phys_start = None
        self._phys_end = None
        self.hide()
        if self.on_cancelled:
            self.on_cancelled()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Yarı saydam nötr grafit ekran karartma
            painter.fillRect(self.rect(), QColor(9, 9, 11, 168))

            # Modern Düz Üst HUD Rehber Kartı
            bw = max(240, min(640, self.width() - 40))
            bh = 58
            bx = max(8, (self.width() - bw) // 2)
            by = 30
            banner_rect = QRect(bx, by, bw, bh)

            painter.setBrush(QColor(18, 18, 22, 246))
            painter.setPen(QPen(QColor(52, 52, 62, 230), 1.0))
            painter.drawRoundedRect(banner_rect, 11, 11)

            ui_font = get_ui_font_family()
            text_left = bx + 18
            if self._logo_pix and not self._logo_pix.isNull():
                painter.drawPixmap(bx + 15, by + (bh - 32) // 2, 32, 32, self._logo_pix)
                text_left = bx + 58

            text_w = max(80, bw - (text_left - bx) - 18)
            title_rect = QRect(text_left, by + 10, text_w, 20)
            sub_rect = QRect(text_left, by + 31, text_w, 18)

            painter.setPen(QColor(250, 250, 250))
            painter.setFont(QFont(ui_font, 10, QFont.Weight.Bold))
            painter.drawText(
                title_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "Altyazı Bölgesini Seçin",
            )

            painter.setPen(QColor(161, 161, 170))
            painter.setFont(QFont(ui_font, 9, QFont.Weight.Medium))
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "İngilizce altyazının çıktığı alanı fareyle sürükleyin   ·   İptal: ESC / Sağ Tık",
            )

            if self.start_pos and self.end_pos:
                sel_rect = QRect(self.start_pos, self.end_pos).normalized()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.fillRect(sel_rect, Qt.GlobalColor.transparent)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

                # Ana Çerçeve (Keskin Düz Beyaz)
                pen = QPen(QColor(250, 250, 250, 215), 1.5, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(sel_rect, 4, 4)

                # Köşe Vurguları (Amber Vizör Köşeleri)
                corner_pen = QPen(
                    QColor(245, 158, 11),
                    2.8,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
                painter.setPen(corner_pen)
                cl = max(4, min(18, sel_rect.width() // 4, sel_rect.height() // 3))
                x1, y1, x2, y2 = (
                    sel_rect.left(),
                    sel_rect.top(),
                    sel_rect.right(),
                    sel_rect.bottom(),
                )

                painter.drawLine(x1, y1, x1 + cl, y1)
                painter.drawLine(x1, y1, x1, y1 + cl)
                painter.drawLine(x2, y1, x2 - cl, y1)
                painter.drawLine(x2, y1, x2, y1 + cl)
                painter.drawLine(x1, y2, x1 + cl, y2)
                painter.drawLine(x1, y2, x1, y2 - cl)
                painter.drawLine(x2, y2, x2 - cl, y2)
                painter.drawLine(x2, y2, x2, y2 - cl)

                # Boyut ve Onay Rozeti
                dim_text = f"{sel_rect.width()} × {sel_rect.height()} px  ·  Bırakın"
                badge_w = 196
                badge_h = 24
                badge_x = max(12, min(sel_rect.left(), self.width() - badge_w - 12))
                badge_y = max(12, sel_rect.top() - badge_h - 8)
                badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

                painter.setBrush(QColor(18, 18, 22, 244))
                painter.setPen(QPen(QColor(58, 58, 68, 220), 1))
                painter.drawRoundedRect(badge_rect, 6, 6)

                painter.setFont(QFont(ui_font, 8, QFont.Weight.DemiBold))
                painter.setPen(QColor(250, 250, 250))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, dim_text)
        finally:
            painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel_selection()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pt = _event_local_point(event)
            self.start_pos = pt
            self.end_pos = pt
            self._phys_start = _get_win32_physical_cursor_pos()
            self._phys_end = self._phys_start
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.is_selecting:
            self.end_pos = _event_local_point(event)
            self._phys_end = _get_win32_physical_cursor_pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_pos = _event_local_point(event)
            self._phys_end = _get_win32_physical_cursor_pos()
            self.hide()

            if self.start_pos and self.end_pos:
                rect = QRect(self.start_pos, self.end_pos).normalized()
                if rect.width() >= 40 and rect.height() >= 18:
                    screen = self._active_screen or QGuiApplication.primaryScreen()
                    dpr = float(screen.devicePixelRatio()) if screen else 1.0
                    sg = screen.geometry() if screen else QRect(0, 0, 1920, 1080)

                    # Global mantıksal Qt koordinatları (Çoklu monitör ofseti dahil)
                    qt_left = int(sg.left() + rect.left())
                    qt_top = int(sg.top() + rect.top())
                    qt_width = int(rect.width())
                    qt_height = int(rect.height())

                    # Fiziksel piksel koordinatları (MSS ekran yakalama için)
                    # Windows karma-DPI çoklu monitörlerde GetCursorPos doğrudan gerçek sanal piksel verir
                    phys_left: Optional[int] = None
                    phys_top: Optional[int] = None
                    phys_width: Optional[int] = None
                    phys_height: Optional[int] = None

                    if self._phys_start and self._phys_end:
                        px1, py1 = self._phys_start
                        px2, py2 = self._phys_end
                        pw = abs(px2 - px1)
                        ph = abs(py2 - py1)
                        exp_w = int(round(qt_width * dpr))
                        exp_h = int(round(qt_height * dpr))
                        if abs(pw - exp_w) <= max(16, int(exp_w * 0.15)) and abs(ph - exp_h) <= max(16, int(exp_h * 0.15)):
                            phys_left = min(px1, px2)
                            phys_top = min(py1, py2)
                            phys_width = max(40, pw)
                            phys_height = max(18, ph)

                    if phys_left is None or phys_top is None or phys_width is None or phys_height is None:
                        if sys.platform == "darwin":
                            # macOS'ta CoreGraphics / MSS ekran yakalama doğrudan mantıksal nokta (point)
                            # koordinatlarını kullanır; Retina DPR ile çarpmak yakalamayı ekran dışına kaydırır.
                            phys_left = qt_left
                            phys_top = qt_top
                            phys_width = max(40, qt_width)
                            phys_height = max(18, qt_height)
                        elif sys.platform == "win32":
                            # Qt6 Windows'ta sg.left()/sg.top() monitör sanal başlangıcıdır;
                            # yalnızca monitör içi göreli ofset DPR ile çarpılır.
                            phys_left = int(sg.left()) + int(round(rect.left() * dpr))
                            phys_top = int(sg.top()) + int(round(rect.top() * dpr))
                            phys_width = max(40, int(round(qt_width * dpr)))
                            phys_height = max(18, int(round(qt_height * dpr)))
                        else:
                            # Linux/X11/Wayland: yalnızca monitör içi göreli ofset DPR ile çarpılır
                            phys_left = int(sg.left()) + int(round(rect.left() * dpr))
                            phys_top = int(sg.top()) + int(round(rect.top() * dpr))
                            phys_width = max(40, int(round(qt_width * dpr)))
                            phys_height = max(18, int(round(qt_height * dpr)))

                    roi = {
                        "left": phys_left,
                        "top": phys_top,
                        "width": phys_width,
                        "height": phys_height,
                        "qt_left": qt_left,
                        "qt_top": qt_top,
                        "qt_width": qt_width,
                        "qt_height": qt_height,
                    }
                    self.on_selected(roi)
                    return

            if self.on_cancelled:
                self.on_cancelled()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_selection()


def compute_autofit_font_size(
    tr_text: str,
    en_text: str,
    avail_w: int,
    avail_h: int,
    max_pt: int = 24,
    min_pt: int = 11,
    orig_line_h: int = 0,
    show_bilingual: bool = False,
    font_family: Optional[str] = None,
) -> int:
    """
    QFontMetrics kullanarak Türkçe altyazının seçili kutuya taşmadan, kırpılmadan
    ve orijinal altyazıyı doğal bir ölçekle örtecek en uygun yazı boyutunu (pt) hesaplar.
    """
    safe_min = max(8, int(min_pt))
    safe_max = max(safe_min, int(max_pt))
    if not tr_text or not tr_text.strip():
        return max(safe_min, min(safe_max, 20))

    family = font_family or get_ui_font_family()
    safe_w = max(120, int(avail_w))
    safe_h = max(36, int(avail_h))
    safe_orig_h = max(0, int(orig_line_h))

    # Orijinal İngilizce satır yüksekliği biliniyorsa doğal eşleşme üst sınırı belirle
    upper_pt = safe_max
    if safe_orig_h > 0:
        natural_pt = int(round(safe_orig_h * 0.80))
        upper_pt = max(safe_min, min(upper_pt, max(14, natural_pt + 4)))

    flags = Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextWordWrap.value
    best_pt = safe_min

    lo, hi = safe_min, upper_pt
    while lo <= hi:
        mid = (lo + hi) // 2
        tr_font = QFont(family, int(mid), QFont.Weight.Bold)
        tr_rect = QFontMetrics(tr_font).boundingRect(QRect(0, 0, safe_w, 4096), flags, tr_text)
        total_h = tr_rect.height()

        if show_bilingual and en_text and en_text.strip():
            en_pt = max(9, int(mid * 0.56))
            en_font = QFont(family, int(en_pt), QFont.Weight.DemiBold)
            en_rect = QFontMetrics(en_font).boundingRect(QRect(0, 0, safe_w, 4096), flags, en_text)
            total_h += en_rect.height() + 4

        if total_h <= safe_h:
            best_pt = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return max(safe_min, min(upper_pt, best_pt))


@dataclass
class _WrappedTextBlock:
    lines: List[str]
    line_widths: List[float]
    line_height: float
    max_width: float
    total_height: float


@dataclass
class DynamicOverlayPlan:
    """Her karede QPainter tarafından çizilecek dinamik sıkı (tight-hug) altyazı planı."""

    tr_font_px: int
    en_font_px: int
    tr_lines: List[str]
    tr_line_rects: List[QRectF]
    en_lines: List[str] = field(default_factory=list)
    en_line_rects: List[QRectF] = field(default_factory=list)
    backdrop_rects: List[QRectF] = field(default_factory=list)
    backdrop_union: QRectF = field(default_factory=QRectF)
    use_stepped_silhouette: bool = False
    corner_radius: float = 8.0


def _make_pixel_font(family: str, px: int, weight: QFont.Weight) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(10, int(px)))
    font.setWeight(weight)
    return font


def _measure_wrapped_text(text: str, font: QFont, max_width: float) -> _WrappedTextBlock:
    """QTextLayout ile her satırın kesin görsel genişliğini ve yüksekliğini ölçer."""
    clean = " ".join((text or "").split())
    if not clean:
        return _WrappedTextBlock([], [], 0.0, 0.0, 0.0)

    safe_max_w = max(40.0, float(max_width))
    fm = QFontMetricsF(font)
    line_h = max(float(fm.height()), float(font.pixelSize() or 14) * 1.18)

    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    opt.setAlignment(Qt.AlignmentFlag.AlignLeft)

    layout = QTextLayout(clean, font)
    layout.setTextOption(opt)
    layout.beginLayout()

    lines: List[str] = []
    line_widths: List[float] = []
    y = 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(safe_max_w)
        line.setPosition(QPointF(0.0, y))
        start = line.textStart()
        length = line.textLength()
        seg = clean[start : start + length].strip()
        if seg:
            lines.append(seg)
            seg_w = max(float(line.naturalTextWidth()), float(fm.horizontalAdvance(seg)))
            line_widths.append(seg_w)
            y += line_h
    layout.endLayout()

    if not lines:
        lines = [clean]
        line_widths = [float(fm.horizontalAdvance(clean))]
        y = line_h

    return _WrappedTextBlock(
        lines=lines,
        line_widths=line_widths,
        line_height=line_h,
        max_width=max(line_widths) if line_widths else 0.0,
        total_height=max(line_h, y),
    )


def _measure_balanced_text(
    text: str, font: QFont, max_width: float, prefer_lines: int = 1
) -> _WrappedTextBlock:
    """
    Tek satıra sığan metni tek satırda bırakır; birden fazla satıra kırılması gerekiyorsa
    sinematik ve dengeli satır genişlikleri seçer (1 dev satır + 1 yetim kelime oluşmasını önler).
    """
    clean = " ".join((text or "").split())
    if not clean:
        return _WrappedTextBlock([], [], 0.0, 0.0, 0.0)

    fm = QFontMetricsF(font)
    single_w = float(fm.horizontalAdvance(clean))
    if single_w <= max_width:
        return _measure_wrapped_text(clean, font, max(single_w + 4.0, max_width))

    base = _measure_wrapped_text(clean, font, max_width)
    n_lines = max(len(base.lines), max(1, int(prefer_lines)))
    if n_lines >= 2:
        balanced_w = min(max_width, max(single_w / float(n_lines) * 1.14, max_width * 0.56))
        cand = _measure_wrapped_text(clean, font, balanced_w)
        if len(cand.lines) <= len(base.lines):
            return cand
    return base


def _clamp_rect_inside(rect: QRectF, bounds: QRectF) -> QRectF:
    """Dikdörtgeni mümkün olduğunca boyutunu koruyarak bounds içine taşır/kırpar."""
    w = min(rect.width(), bounds.width())
    h = min(rect.height(), bounds.height())
    x = max(bounds.left(), min(rect.left(), bounds.right() - w))
    y = max(bounds.top(), min(rect.top(), bounds.bottom() - h))
    return QRectF(x, y, w, h)


def compute_dynamic_overlay_plan(
    tr_text: str,
    en_text: str,
    canvas_rect: QRect,
    local_roi_rect: QRect,
    layout: Optional[Dict],
    overlay_mode: str = "cover",
    font_size_pt: int = 22,
    auto_fit_font: bool = True,
    show_bilingual: bool = False,
    orig_line_h_logical: int = 0,
    logical_dpi_y: float = 96.0,
    font_family: Optional[str] = None,
) -> Optional[DynamicOverlayPlan]:
    """
    Orijinal altyazının tam OCR sınır kutusuna (bbox / lines) sıkıca hizalanan,
    ekstra alan kaplamayan ve yalnızca Türkçe çeviri orijinal kutudan uzadığında
    kontrollü şekilde genişleyen (Videoyun / GTA 6 tarzı) dinamik çizim planı üretir.
    """
    clean_tr = " ".join((tr_text or "").split())
    if not clean_tr:
        return None

    clean_en = " ".join((en_text or "").split()) if show_bilingual else ""
    family = font_family or get_ui_font_family()
    dpi_scale = max(72.0, float(logical_dpi_y)) / 72.0
    max_px = max(13, int(round(int(font_size_pt) * dpi_scale)))
    min_px = 12

    canvas_safe = QRectF(canvas_rect).adjusted(3.0, 3.0, -3.0, -3.0)
    if canvas_safe.width() < 40.0 or canvas_safe.height() < 24.0:
        return None

    roi_f = QRectF(local_roi_rect)
    orig_rect: Optional[QRectF] = None
    orig_line_rects: List[QRectF] = []
    orig_line_count = 1
    h_line = float(max(0, int(orig_line_h_logical)))

    if layout and isinstance(layout, dict) and layout.get("bbox") and roi_f.width() > 0 and roi_f.height() > 0:
        try:
            u1, v1, u2, v2 = layout["bbox"]
            ow = max(20.0, (float(u2) - float(u1)) * roi_f.width())
            oh = max(14.0, (float(v2) - float(v1)) * roi_f.height())
            orig_rect = QRectF(roi_f.left() + float(u1) * roi_f.width(), roi_f.top() + float(v1) * roi_f.height(), ow, oh)
            for lb in layout.get("lines") or []:
                lu1, lv1, lu2, lv2 = lb
                lw = max(16.0, (float(lu2) - float(lu1)) * roi_f.width())
                lh = max(12.0, (float(lv2) - float(lv1)) * roi_f.height())
                orig_line_rects.append(
                    QRectF(roi_f.left() + float(lu1) * roi_f.width(), roi_f.top() + float(lv1) * roi_f.height(), lw, lh)
                )
            norm_lh = float(layout.get("line_h_norm") or 0.0)
            if norm_lh > 0.0:
                h_line = norm_lh * roi_f.height()
            orig_line_count = max(1, int(layout.get("line_count") or len(orig_line_rects) or 1))
        except Exception:
            orig_rect = None
            orig_line_rects = []

    ref_h = h_line if h_line >= 10.0 else float(max_px)
    pad_x = max(10.0, round(ref_h * 0.36))
    pad_y = max(5.0, round(ref_h * 0.22))

    # Orijinal satır yüksekliğine doğal eşleşme (Auto-Fit)
    if auto_fit_font and h_line >= 10.0:
        target_px = max(min_px, min(max_px, int(round(h_line * 1.06))))
    else:
        target_px = max_px

    is_cover_with_bbox = (overlay_mode == "cover") and (orig_rect is not None)
    max_canvas_text_w = max(100.0, canvas_safe.width() - 2.0 * pad_x)

    if is_cover_with_bbox and orig_rect is not None:
        cx = orig_rect.center().x()
        cy = orig_rect.center().y()
        w_orig = orig_rect.width()
        h_orig = orig_rect.height()
        w_expand_limit = min(
            max(roi_f.width(), w_orig * 1.85, 360.0),
            max_canvas_text_w,
        )
    else:
        cx = orig_rect.center().x() if orig_rect is not None else roi_f.center().x()
        cy = canvas_safe.center().y()
        w_orig = min(max_canvas_text_w, max(160.0, roi_f.width() * 0.94))
        h_orig = max(24.0, roi_f.height())
        w_expand_limit = max_canvas_text_w

    # Metni hedef fontta ölç; gerekirse yalnızca aşırı taşmada fontu küçült
    chosen_px = target_px
    chosen_en_px = max(10, int(round(chosen_px * 0.58)))
    tr_block = _WrappedTextBlock([], [], 0.0, 0.0, 0.0)
    en_block = _WrappedTextBlock([], [], 0.0, 0.0, 0.0)

    while True:
        tr_font = _make_pixel_font(family, chosen_px, QFont.Weight.Bold)
        fm_tr = QFontMetricsF(tr_font)
        single_w = float(fm_tr.horizontalAdvance(clean_tr))

        if is_cover_with_bbox and orig_rect is not None:
            if orig_line_count == 1:
                if single_w <= w_orig + 4.0:
                    # Tam orijinal kutunun içine sığıyor — sıfır ekstra alan!
                    tr_block = _measure_wrapped_text(clean_tr, tr_font, max(w_orig + 4.0, single_w + 4.0))
                elif single_w <= w_expand_limit:
                    # 2 kelimelik cümle TR'de 5 kelimeye çıktı: tek satırda kontrollü yatay genişleme
                    tr_block = _measure_wrapped_text(clean_tr, tr_font, single_w + 4.0)
                else:
                    # Çok uzun cümle: dengeli 2+ satıra kır
                    tr_block = _measure_balanced_text(clean_tr, tr_font, w_expand_limit, prefer_lines=2)
            else:
                # Çok satırlı orijinal altyazı: önce orijinal genişliği dene
                tight_try = _measure_wrapped_text(clean_tr, tr_font, max(w_orig + 8.0, 120.0))
                if len(tight_try.lines) <= orig_line_count and tight_try.total_height <= h_orig + 10.0:
                    tr_block = tight_try
                else:
                    wrap_cap = min(w_expand_limit, max(w_orig * 1.25, roi_f.width() * 0.92))
                    tr_block = _measure_balanced_text(
                        clean_tr, tr_font, wrap_cap, prefer_lines=orig_line_count
                    )
        else:
            tr_block = _measure_balanced_text(clean_tr, tr_font, w_orig, prefer_lines=1)

        en_extra_h = 0.0
        en_gap = 3.0
        if clean_en:
            chosen_en_px = max(10, int(round(chosen_px * 0.58)))
            en_font = _make_pixel_font(family, chosen_en_px, QFont.Weight.DemiBold)
            en_wrap_w = max(tr_block.max_width, w_orig if is_cover_with_bbox else 140.0)
            en_wrap_w = min(en_wrap_w, max_canvas_text_w)
            en_block = _measure_balanced_text(clean_en, en_font, en_wrap_w, prefer_lines=1)
            en_extra_h = en_block.total_height + en_gap
        else:
            en_block = _WrappedTextBlock([], [], 0.0, 0.0, 0.0)

        needed_h = tr_block.total_height + en_extra_h + 2.0 * pad_y
        if needed_h <= canvas_safe.height() or chosen_px <= min_px:
            break
        chosen_px = max(min_px, chosen_px - 1)

    # Çeviri bloğunu tam hedef merkezine (cx, cy) yerleştir, ekran kenarından taşmasını engelle
    text_bounds = canvas_safe.adjusted(pad_x, pad_y, -pad_x, -pad_y)
    total_text_h = tr_block.total_height + (en_block.total_height + 3.0 if en_block.lines else 0.0)
    block_w = max(tr_block.max_width, en_block.max_width)

    if is_cover_with_bbox and orig_rect is not None:
        # Orijinal kutuyla aynı dikey merkez; eğer alt kenara yakınsa yukarı doğru genişle
        desired_top = cy - total_text_h * 0.5
        if en_block.lines:
            # Çift dilli modda TR satırını orijinalin üstünde tut, EN üstüne çıksın
            desired_top = (cy - tr_block.total_height * 0.5) - (en_block.total_height + 3.0)
        if desired_top + total_text_h > text_bounds.bottom():
            desired_top = text_bounds.bottom() - total_text_h
        desired_top = max(text_bounds.top(), desired_top)
    elif overlay_mode == "above":
        # 'above' modunda ROI'nin hemen üstüne yasla (canvas alt kenarına yakın)
        desired_top = max(text_bounds.top(), text_bounds.bottom() - total_text_h)
    else:
        desired_top = max(text_bounds.top(), min(cy - total_text_h * 0.5, text_bounds.bottom() - total_text_h))

    desired_left = max(text_bounds.left(), min(cx - block_w * 0.5, text_bounds.right() - block_w))
    block_cx = desired_left + block_w * 0.5

    en_line_rects: List[QRectF] = []
    cur_y = desired_top
    if en_block.lines:
        for lw in en_block.line_widths:
            en_line_rects.append(QRectF(block_cx - lw * 0.5, cur_y, lw, en_block.line_height))
            cur_y += en_block.line_height
        cur_y += 3.0

    tr_line_rects: List[QRectF] = []
    for lw in tr_block.line_widths:
        tr_line_rects.append(QRectF(block_cx - lw * 0.5, cur_y, lw, tr_block.line_height))
        cur_y += tr_block.line_height

    # Arka plan kutularını oluştur:
    # 'cover' + bbox modunda orijinal İngilizce kutunun %100 örtülmesi GARANTİ edilir!
    backdrop_rects: List[QRectF] = []
    if is_cover_with_bbox and orig_rect is not None:
        if orig_line_rects:
            for r in orig_line_rects:
                backdrop_rects.append(_clamp_rect_inside(r.adjusted(-pad_x, -pad_y, pad_x, pad_y), canvas_safe))
        else:
            backdrop_rects.append(_clamp_rect_inside(orig_rect.adjusted(-pad_x, -pad_y, pad_x, pad_y), canvas_safe))

    for r in en_line_rects:
        backdrop_rects.append(_clamp_rect_inside(r.adjusted(-pad_x, -pad_y * 0.8, pad_x, pad_y * 0.8), canvas_safe))
    for r in tr_line_rects:
        backdrop_rects.append(_clamp_rect_inside(r.adjusted(-pad_x, -pad_y, pad_x, pad_y), canvas_safe))

    union_rect = QRectF(backdrop_rects[0])
    for r in backdrop_rects[1:]:
        union_rect = union_rect.united(r)
    union_rect = _clamp_rect_inside(union_rect, canvas_safe)

    # Çok satırlı ve satır genişlikleri belirgin biçimde farklı altyazılarda basamaklı silüet kullan
    all_widths = [r.width() for r in backdrop_rects if r.width() > 0]
    use_stepped = False
    if len(tr_line_rects) >= 2 and all_widths:
        if min(all_widths) < max(all_widths) * 0.78:
            use_stepped = True

    corner_radius = max(5.0, min(10.0, union_rect.height() * 0.22))

    return DynamicOverlayPlan(
        tr_font_px=int(chosen_px),
        en_font_px=int(chosen_en_px),
        tr_lines=tr_block.lines,
        tr_line_rects=tr_line_rects,
        en_lines=en_block.lines,
        en_line_rects=en_line_rects,
        backdrop_rects=backdrop_rects,
        backdrop_union=union_rect,
        use_stepped_silhouette=use_stepped,
        corner_radius=corner_radius,
    )


class SubtitleOverlayWindow(QWidget):
    """
    Oyun, dizi veya film üzerinde tıklamaları arkaya geçiren (Click-Through),
    her zaman üstte duran ve WDA_EXCLUDEFROMCAPTURE ile OCR'a görünmez olan dinamik Türkçe altyazı katmanı.
    Yalnızca algılanan orijinal altyazının boyutunu sıkıca örter (GTA 6 / Videoyun tarzı),
    tüm ROI bölgesini gereksiz yere karartmaz.
    """

    def __init__(self):
        super().__init__()
        self.font_size = 22
        self._active_font_size = 22
        self.auto_fit_font = True
        self.text_color = "#FFFFFF"
        self.bg_alpha = 225
        self.overlay_mode = "cover"  # 'cover' (Orijinalin Tam Üstünü Kapat) veya 'above' (Hemen Üstünde)
        self._effective_mode = "cover"
        self.show_guide_border = False
        self.show_bilingual = False
        self.capture_excluded = False

        self._current_tr = ""
        self._current_en = ""
        self._current_layout: Optional[Dict] = None
        self._last_orig_line_h = 0
        self._last_roi: Optional[Dict[str, int]] = None
        self._roi_rect = QRect(0, 0, 800, 105)
        self._canvas_rect = QRect(0, 0, 800, 105)
        self._local_roi_rect = QRect(0, 0, 800, 105)
        self._render_plan: Optional[DynamicOverlayPlan] = None

        if sys.platform == "darwin":
            # macOS'ta Qt.WindowType.Tool pencereyi uygulama odak kaybedince gizler;
            # bunun yerine odak almayan, her zaman üstte duran çerçevesiz pencere kullanılır.
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowTransparentForInput
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowTransparentForInput
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        screen = QGuiApplication.primaryScreen()
        if screen:
            sg = screen.geometry()
            w = int(sg.width() * 0.58)
            h = 105
            x = sg.left() + (sg.width() - w) // 2
            y = sg.top() + sg.height() - h - 75
            self._roi_rect = QRect(x, y, w, h)
            self._canvas_rect = QRect(x, y, w, h)
            self._local_roi_rect = QRect(0, 0, w, h)
            self.setGeometry(self._canvas_rect)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        _configure_macos_overlay_window(self)
        self.capture_excluded = set_window_exclude_from_capture(self, True)

    def _smooth_layout_if_same_sentence(
        self, en_text: str, new_layout: Optional[Dict]
    ) -> Optional[Dict]:
        """Aynı cümle ekranda kalırken 1-3 px'lik OCR titremelerini (jitter) bastırır."""
        if (
            not new_layout
            or not self._current_layout
            or not en_text
            or en_text != self._current_en
            or not new_layout.get("bbox")
            or not self._current_layout.get("bbox")
        ):
            return new_layout

        rw = max(1.0, float(self._local_roi_rect.width()))
        rh = max(1.0, float(self._local_roi_rect.height()))
        pu1, pv1, pu2, pv2 = self._current_layout["bbox"]
        nu1, nv1, nu2, nv2 = new_layout["bbox"]
        dx1 = abs(nu1 - pu1) * rw
        dx2 = abs(nu2 - pu2) * rw
        dy1 = abs(nv1 - pv1) * rh
        dy2 = abs(nv2 - pv2) * rh
        if max(dx1, dx2, dy1, dy2) <= 3.0 and new_layout.get("line_count") == self._current_layout.get("line_count"):
            return self._current_layout
        return new_layout

    def _rebuild_render_plan(self) -> None:
        if not self._current_tr.strip():
            self._render_plan = None
            return

        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        dpi_y = float(screen.logicalDotsPerInchY()) if screen else 96.0
        self._render_plan = compute_dynamic_overlay_plan(
            tr_text=self._current_tr,
            en_text=self._current_en,
            canvas_rect=self.rect(),
            local_roi_rect=self._local_roi_rect,
            layout=self._current_layout,
            overlay_mode=self._effective_mode,
            font_size_pt=int(self.font_size),
            auto_fit_font=bool(self.auto_fit_font),
            show_bilingual=bool(self.show_bilingual),
            orig_line_h_logical=int(self._last_orig_line_h),
            logical_dpi_y=dpi_y,
        )
        if self._render_plan is not None:
            self._active_font_size = max(10, int(round(self._render_plan.tr_font_px * 72.0 / max(72.0, dpi_y))))

    def update_appearance(
        self,
        font_size: Optional[int] = None,
        text_color: Optional[str] = None,
        bg_alpha: Optional[int] = None,
        overlay_mode: Optional[str] = None,
        show_bilingual: Optional[bool] = None,
        auto_fit_font: Optional[bool] = None,
    ) -> None:
        if font_size is not None:
            self.font_size = max(10, min(48, int(round(font_size))))
        if text_color is not None:
            self.text_color = str(text_color)
        if bg_alpha is not None:
            self.bg_alpha = max(0, min(255, int(round(bg_alpha))))
        if overlay_mode is not None:
            self.overlay_mode = str(overlay_mode)
            effective_mode = self.overlay_mode
            if effective_mode == "cover" and not self.capture_excluded:
                effective_mode = "above"
            self._effective_mode = effective_mode
        if show_bilingual is not None:
            self.show_bilingual = bool(show_bilingual)
        if auto_fit_font is not None:
            self.auto_fit_font = bool(auto_fit_font)

        self._rebuild_render_plan()
        self.update()

    def align_to_roi(self, roi: Dict[str, int]) -> None:
        """
        Seçilen İngilizce altyazı bölgesine göre şeffaf ev sahibi tuvali (host canvas)
        bir kez konumlandırır. Gerçek altyazı arka planı bu tuvalin tamamını değil,
        yalnızca tespit edilen orijinal altyazı kutusunu dinamik olarak boyar.
        """
        self._last_roi = dict(roi)
        x = int(round(roi.get("qt_left", roi["left"])))
        y = int(round(roi.get("qt_top", roi["top"])))
        w = max(40, int(round(roi.get("qt_width", roi["width"]))))
        h = max(18, int(round(roi.get("qt_height", roi["height"]))))

        self.capture_excluded = set_window_exclude_from_capture(self, True)
        effective_mode = self.overlay_mode
        if effective_mode == "cover" and not self.capture_excluded:
            effective_mode = "above"
        self._effective_mode = effective_mode

        self._roi_rect = QRect(x, y, w, h)
        screen = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2)) or QGuiApplication.primaryScreen()
        sg = screen.geometry().adjusted(4, 4, -4, -4) if screen else QRect(4, 4, 1912, 1072)

        overflow_x = min(220, int(sg.width() * 0.14))
        if effective_mode == "cover":
            # Çeviri orijinal kutudan uzadığında pencereyi yeniden boyutlandırmadan (titremesiz)
            # genişleyebilmesi için çevresinde şeffaf taşma payı bırakılır.
            overflow_top = 72
            overflow_bottom = 36
            expanded = self._roi_rect.adjusted(-overflow_x, -overflow_top, overflow_x, overflow_bottom)
            canvas = expanded.intersected(sg)
            if canvas.width() < 40 or canvas.height() < 24:
                canvas = self._roi_rect.intersected(sg)
            if canvas.width() < 40 or canvas.height() < 24:
                canvas = QRect(x, y, w, h)
            self._canvas_rect = canvas
            self._local_roi_rect = self._roi_rect.translated(-self._canvas_rect.topLeft())
        else:
            min_h = 110 if self.show_bilingual else 84
            box_h = max(h + 24, min_h)
            c_left = max(sg.left(), x - overflow_x)
            c_right = min(sg.right(), x + w + overflow_x)
            c_w = max(w, c_right - c_left)
            above_y = y - box_h - 6
            if above_y >= sg.top():
                target_y = above_y
            else:
                target_y = min(sg.bottom() - box_h, y + h + 6)
            self._canvas_rect = QRect(int(c_left), int(target_y), int(c_w), int(box_h))
            self._local_roi_rect = QRect(
                int(x - self._canvas_rect.left()),
                0,
                int(w),
                int(box_h),
            )

        self.setGeometry(self._canvas_rect)
        self._rebuild_render_plan()
        self.update()

    def set_subtitle(
        self,
        tr_text: str,
        en_text: str = "",
        orig_line_h_px: int = 0,
        layout: Optional[Dict] = None,
    ) -> None:
        tr_str = str(tr_text or "")
        en_str = str(en_text or "")

        if not tr_str.strip():
            if not self._current_tr and self._render_plan is None:
                return
            self._current_tr = ""
            self._current_en = ""
            self._current_layout = None
            self._last_orig_line_h = 0
            self._render_plan = None
            self.update()
            return

        smoothed_layout = self._smooth_layout_if_same_sentence(en_str, layout)
        if (
            tr_str == self._current_tr
            and en_str == self._current_en
            and int(orig_line_h_px) == 0
            and smoothed_layout == self._current_layout
        ):
            return

        self._current_tr = tr_str
        self._current_en = en_str
        self._current_layout = smoothed_layout

        if orig_line_h_px and int(orig_line_h_px) > 0:
            screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
            dpr = float(screen.devicePixelRatio()) if screen else 1.0
            self._last_orig_line_h = max(10, int(round(int(orig_line_h_px) / max(1.0, dpr))))

        self._rebuild_render_plan()
        self.update()

    def set_guide_border(self, enabled: bool) -> None:
        self.show_guide_border = bool(enabled)
        self.update()

    @staticmethod
    def _build_backdrop_path(plan: DynamicOverlayPlan) -> QPainterPath:
        radius = float(plan.corner_radius)
        if not plan.use_stepped_silhouette or len(plan.backdrop_rects) <= 1:
            path = QPainterPath()
            path.addRoundedRect(plan.backdrop_union, radius, radius)
            return path

        # Çok satırlı basamaklı silüet: her satırı kendi sıkı kutusunda birleştirir
        merged = QPainterPath()
        merged.setFillRule(Qt.FillRule.WindingFill)
        sorted_rects = sorted(plan.backdrop_rects, key=lambda r: r.top())
        for idx, r in enumerate(sorted_rects):
            seg = QRectF(r)
            # Bitişik satırlar arasında ince şeffaf yarık oluşmaması için 2px dikey köprü
            if idx + 1 < len(sorted_rects):
                nxt = sorted_rects[idx + 1]
                gap = nxt.top() - seg.bottom()
                if 0.0 < gap <= 10.0:
                    seg.setBottom(nxt.top() + 2.0)
            p = QPainterPath()
            p.addRoundedRect(seg, radius, radius)
            merged = merged.united(p)
        return merged

    @staticmethod
    def _draw_outlined_text(
        painter: QPainter,
        rect: QRectF,
        text: str,
        text_color: QColor,
        shadow_alpha: int = 235,
    ) -> None:
        """Düşük gecikmeli, keskin koyu kontür + gölge destekli altyazı metni çizer."""
        align = Qt.AlignmentFlag.AlignCenter
        shadow_color = QColor(0, 0, 0, max(0, min(255, int(shadow_alpha))))
        painter.setPen(shadow_color)
        for dx, dy in ((-1.2, 0.0), (1.2, 0.0), (0.0, -1.2), (0.0, 1.2), (1.4, 1.8)):
            painter.drawText(rect.translated(dx, dy), align, text)
        painter.setPen(text_color)
        painter.drawText(rect, align, text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            # 1) Hizalama rehber çerçevesi açıksa tam seçili ROI sınırını göster
            if self.show_guide_border:
                roi_box = QRectF(self._local_roi_rect).adjusted(1.5, 1.5, -1.5, -1.5)
                if not self._render_plan:
                    painter.setBrush(QColor(12, 12, 14, 115))
                else:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(245, 158, 11, 210), 1.4, Qt.PenStyle.DashLine))
                painter.drawRoundedRect(roi_box, 8.0, 8.0)

            # 2) Aktif altyazı varsa YALNIZCA sıkı hesaplanan arka planı ve metni çiz
            plan = self._render_plan
            if plan is None:
                return

            alpha = max(0, min(255, int(self.bg_alpha)))
            bg_path = self._build_backdrop_path(plan)
            painter.setBrush(QColor(12, 12, 14, alpha))
            painter.setPen(QPen(QColor(255, 255, 255, 22), 1.0, Qt.PenStyle.SolidLine))
            painter.drawPath(bg_path)

            ui_font = get_ui_font_family()
            if plan.en_lines:
                en_font = _make_pixel_font(ui_font, plan.en_font_px, QFont.Weight.DemiBold)
                painter.setFont(en_font)
                en_color = QColor("#D4D4D8")
                for line_txt, rect in zip(plan.en_lines, plan.en_line_rects):
                    self._draw_outlined_text(painter, rect, line_txt, en_color, shadow_alpha=200)

            tr_font = _make_pixel_font(ui_font, plan.tr_font_px, QFont.Weight.Bold)
            painter.setFont(tr_font)
            tr_color = QColor(self.text_color)
            if not tr_color.isValid():
                tr_color = QColor("#FFFFFF")
            for line_txt, rect in zip(plan.tr_lines, plan.tr_line_rects):
                self._draw_outlined_text(painter, rect, line_txt, tr_color, shadow_alpha=240)
        finally:
            painter.end()
