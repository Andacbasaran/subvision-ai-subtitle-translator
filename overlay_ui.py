"""
SubVision AI — PyQt6 Şeffaf Altyazı Katmanı (Click-Through Overlay) ve Çoklu Monitör / 4K DPI Uyumlu Alan Seçici (ROI Selector).
Windows WDA_EXCLUDEFROMCAPTURE (0x11) özelliği sayesinde Türkçe altyazı kutusu,
orijinal İngilizce altyazının tam üstünü kapatsa bile ekran yakalayıcı (MSS) tarafından görülmez.
Oyunlar, Diziler, Filmler ve Yayınlar ile %100 uyumludur.
"""

import ctypes
from typing import Callable, Dict, Optional

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def set_window_exclude_from_capture(widget: QWidget, exclude: bool = True) -> bool:
    """
    Windows 10 (2004+) / Windows 11 API:
    Pencereyi kullanıcının gözüne görünür tutar ancak ekran yakalama (MSS/OCR) için
    %100 görünmez yapar. Böylece Türkçe altyazı, İngilizce altyazının tam üzerine
    yerleştirilse bile OCR kendi yazdığı Türkçe metni okumaz.
    """
    try:
        hwnd = int(widget.winId())
        flag = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
        res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, flag)
        return bool(res)
    except Exception:
        return False


class ROISelectorOverlay(QWidget):
    """
    Fare ile ekranda oyun, dizi, film veya video oynatıcının İngilizce altyazısının
    çıktığı alanı (ROI) seçme ekranı. Çoklu monitör ve 4K yüksek DPI (%125-%200) uyumludur.
    """

    def __init__(self, on_selected: Callable[[Dict[str, int]], None]):
        super().__init__()
        self.on_selected = on_selected
        self.start_pos: Optional[QPoint] = None
        self.end_pos: Optional[QPoint] = None
        self.is_selecting = False
        self._active_screen = QGuiApplication.primaryScreen()

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
        self.is_selecting = False

        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        self._active_screen = screen
        if screen:
            self.setGeometry(screen.geometry())

        self.show()
        self.activateWindow()
        self.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Yarı saydam sinematik karartma
        painter.fillRect(self.rect(), QColor(6, 10, 20, 150))

        # Modern Üst HUD Bilgi Kartı
        bw = min(820, self.width() - 40)
        bx = (self.width() - bw) // 2
        banner_rect = QRect(bx, 32, bw, 62)

        painter.setBrush(QColor(15, 23, 42, 240))
        painter.setPen(QPen(QColor(56, 189, 248, 180), 1.5))
        painter.drawRoundedRect(banner_rect, 14, 14)

        painter.setPen(QColor(248, 250, 252))
        font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(
            banner_rect,
            Qt.AlignmentFlag.AlignCenter,
            "🎯 Oyun, Dizi veya Filmdeki Altyazı Bölgesini Fare İle Seçin   •   İptal: ESC",
        )

        if self.start_pos and self.end_pos:
            sel_rect = QRect(self.start_pos, self.end_pos).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(sel_rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # Ana Çerçeve
            pen = QPen(QColor(56, 189, 248, 220), 1.5, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sel_rect)

            # Köşe Vurguları (Viewfinder Corner Brackets)
            corner_pen = QPen(QColor(34, 197, 94), 3.0, Qt.PenStyle.SolidLine)
            painter.setPen(corner_pen)
            cl = min(18, sel_rect.width() // 4, sel_rect.height() // 3)
            x1, y1, x2, y2 = sel_rect.left(), sel_rect.top(), sel_rect.right(), sel_rect.bottom()

            # Sol-Üst
            painter.drawLine(x1, y1, x1 + cl, y1)
            painter.drawLine(x1, y1, x1, y1 + cl)
            # Sağ-Üst
            painter.drawLine(x2, y1, x2 - cl, y1)
            painter.drawLine(x2, y1, x2, y1 + cl)
            # Sol-Alt
            painter.drawLine(x1, y2, x1 + cl, y2)
            painter.drawLine(x1, y2, x1, y2 - cl)
            # Sağ-Alt
            painter.drawLine(x2, y2, x2 - cl, y2)
            painter.drawLine(x2, y2, x2, y2 - cl)

            # Boyut Rozeti (Dimensions Pill)
            dim_text = f"📏 {sel_rect.width()} × {sel_rect.height()} px"
            badge_w = 148
            badge_h = 26
            badge_x = sel_rect.left()
            badge_y = max(12, sel_rect.top() - badge_h - 6)
            badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

            painter.setBrush(QColor(15, 23, 42, 230))
            painter.setPen(QPen(QColor(34, 197, 94, 200), 1))
            painter.drawRoundedRect(badge_rect, 6, 6)

            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.setPen(QColor(74, 222, 128))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, dim_text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.pos()
            self.end_pos = event.pos()
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.is_selecting:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_pos = event.pos()
            self.hide()

            if self.start_pos and self.end_pos:
                rect = QRect(self.start_pos, self.end_pos).normalized()
                if rect.width() >= 40 and rect.height() >= 18:
                    screen = self._active_screen or QGuiApplication.primaryScreen()
                    dpr = screen.devicePixelRatio() if screen else 1.0
                    sg = screen.geometry() if screen else QRect(0, 0, 1920, 1080)

                    # Global mantıksal Qt koordinatları (Çoklu monitör ofseti dahil)
                    qt_left = sg.left() + rect.left()
                    qt_top = sg.top() + rect.top()
                    qt_width = rect.width()
                    qt_height = rect.height()

                    # Fiziksel piksel koordinatları (MSS ekran yakalama için)
                    roi = {
                        "left": int(round(qt_left * dpr)),
                        "top": int(round(qt_top * dpr)),
                        "width": int(round(qt_width * dpr)),
                        "height": int(round(qt_height * dpr)),
                        "qt_left": qt_left,
                        "qt_top": qt_top,
                        "qt_width": qt_width,
                        "qt_height": qt_height,
                    }
                    self.on_selected(roi)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.is_selecting = False
            self.hide()


class SubtitleOverlayWindow(QWidget):
    """
    Oyun, dizi veya film üzerinde tıklamaları arkaya geçiren (Click-Through),
    her zaman üstte duran ve WDA_EXCLUDEFROMCAPTURE ile OCR'a görünmez olan Türkçe altyazı katmanı.
    İsteğe bağlı Çift Dilli (EN + TR) gösterim modunu destekler.
    """

    def __init__(self):
        super().__init__()
        self.font_size = 21
        self.text_color = "#FFFFFF"
        self.bg_alpha = 225
        self.overlay_mode = "cover"  # 'cover' (Orijinalin Tam Üstünü Kapat) veya 'above' (Hemen Üstünde)
        self.show_guide_border = False
        self.show_bilingual = False
        self._current_tr = ""
        self._current_en = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(2)

        # İkincil (İngilizce Orijinal) Satır - Çift Dilli Mod aktifken görünür
        self.en_label = QLabel("")
        self.en_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.en_label.setWordWrap(True)
        self.en_label.hide()

        # Ana (Türkçe Çeviri) Satırı
        self.label = QLabel("")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)

        shadow = QGraphicsDropShadowEffect(self.label)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 255))
        shadow.setOffset(2, 2)
        self.label.setGraphicsEffect(shadow)

        layout.addWidget(self.en_label)
        layout.addWidget(self.label)
        self._apply_text_style()

        screen = QGuiApplication.primaryScreen()
        if screen:
            sg = screen.geometry()
            w = int(sg.width() * 0.58)
            h = 105
            x = sg.left() + (sg.width() - w) // 2
            y = sg.top() + sg.height() - h - 75
            self.setGeometry(x, y, w, h)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_window_exclude_from_capture(self, True)

    def _apply_text_style(self) -> None:
        en_size = max(10, int(self.font_size * 0.58))
        self.en_label.setStyleSheet(
            f"""
            QLabel {{
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: {en_size}pt;
                font-weight: 600;
                background: transparent;
            }}
            """
        )
        self.label.setStyleSheet(
            f"""
            QLabel {{
                color: {self.text_color};
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: {self.font_size}pt;
                font-weight: 700;
                background: transparent;
            }}
            """
        )

    def update_appearance(
        self,
        font_size: Optional[int] = None,
        text_color: Optional[str] = None,
        bg_alpha: Optional[int] = None,
        overlay_mode: Optional[str] = None,
        show_bilingual: Optional[bool] = None,
    ) -> None:
        if font_size is not None:
            self.font_size = font_size
        if text_color is not None:
            self.text_color = text_color
        if bg_alpha is not None:
            self.bg_alpha = bg_alpha
        if overlay_mode is not None:
            self.overlay_mode = overlay_mode
        if show_bilingual is not None:
            self.show_bilingual = show_bilingual
            self._refresh_labels()
        self._apply_text_style()
        self.update()

    def align_to_roi(self, roi: Dict[str, int]) -> None:
        """
        Seçilen İngilizce altyazı bölgesine göre Türkçe altyazı kutusunu hizalar.
        """
        x = roi.get("qt_left", roi["left"])
        y = roi.get("qt_top", roi["top"])
        w = roi.get("qt_width", roi["width"])
        h = roi.get("qt_height", roi["height"])

        min_h = 84 if self.show_bilingual else 64
        if self.overlay_mode == "cover":
            self.setGeometry(x, y, w, max(h, min_h))
        else:
            box_h = max(h, min_h + 12)
            self.setGeometry(x, max(10, y - box_h - 6), w, box_h)

        set_window_exclude_from_capture(self, True)
        self.update()

    def _refresh_labels(self) -> None:
        if self.show_bilingual and self._current_en.strip() and self._current_tr.strip():
            self.en_label.setText(self._current_en)
            self.en_label.show()
        else:
            self.en_label.setText("")
            self.en_label.hide()
        self.label.setText(self._current_tr)

    def set_subtitle(self, tr_text: str, en_text: str = "") -> None:
        if tr_text == self._current_tr and en_text == self._current_en:
            return
        self._current_tr = tr_text
        self._current_en = en_text
        self._refresh_labels()
        self.update()

    def set_guide_border(self, enabled: bool) -> None:
        self.show_guide_border = enabled
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        has_text = bool(self._current_tr.strip())
        if has_text or self.show_guide_border:
            bg_color = QColor(8, 12, 22, self.bg_alpha if has_text else 120)
            painter.setBrush(bg_color)
            if self.show_guide_border:
                painter.setPen(QPen(QColor(56, 189, 248, 230), 2, Qt.PenStyle.DashLine))
            else:
                painter.setPen(QPen(QColor(255, 255, 255, 26), 1, Qt.PenStyle.SolidLine))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 12, 12)
