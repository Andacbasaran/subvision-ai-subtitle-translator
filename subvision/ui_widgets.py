"""
SubVision AI — Reusable HiDPI PyQt6 UI Widgets & Vector Icon Helpers.
Studio 2.0 (Monolith / Studio Graphite) flat design system — crisp geometric icons,
sidebar nav items, circular color swatches, monochrome toggles, and flat telemetry cards.
"""

import os
import sys
from typing import Optional

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hardware import get_app_base_dir, get_ui_font_family


def make_flat_icon(kind: str, color_hex: str = "#FAFAFA", size: int = 14) -> QIcon:
    """
    Emoji bağımlılığı olmadan tüm işletim sistemlerinde net görünen
    vektörel (2x HiDPI) minimalist arayüz ikonları üretir.
    """
    px = max(16, int(size) * 2)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(color_hex)

        if kind == "dot":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            r = px * 0.32
            p.drawEllipse(QPointF(px / 2.0, px / 2.0), r, r)
        elif kind == "play":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            poly = QPolygonF(
                [
                    QPointF(px * 0.28, px * 0.18),
                    QPointF(px * 0.82, px * 0.50),
                    QPointF(px * 0.28, px * 0.82),
                ]
            )
            p.drawPolygon(poly)
        elif kind == "stop":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(
                int(px * 0.22), int(px * 0.22), int(px * 0.56), int(px * 0.56), 4, 4
            )
        elif kind == "target":
            pen = QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            m = int(px * 0.16)
            e = px - m
            l_seg = int(px * 0.24)
            p.drawLine(m, m, m + l_seg, m)
            p.drawLine(m, m, m, m + l_seg)
            p.drawLine(e, m, e - l_seg, m)
            p.drawLine(e, m, e, m + l_seg)
            p.drawLine(m, e, m + l_seg, e)
            p.drawLine(m, e, m, e - l_seg)
            p.drawLine(e, e, e - l_seg, e)
            p.drawLine(e, e, e, e - l_seg)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(px / 2.0, px / 2.0), 2.2, 2.2)
        elif kind == "preview":
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                int(px * 0.14), int(px * 0.22), int(px * 0.72), int(px * 0.56), 4, 4
            )
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
            p.drawRoundedRect(
                int(px * 0.34), int(px * 0.30), int(px * 0.50), int(px * 0.54), 3, 3
            )
            p.drawLine(int(px * 0.22), int(px * 0.68), int(px * 0.22), int(px * 0.20))
            p.drawLine(int(px * 0.22), int(px * 0.20), int(px * 0.64), int(px * 0.20))
        elif kind == "manage":
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                int(px * 0.18), int(px * 0.22), int(px * 0.64), int(px * 0.60), 4, 4
            )
            p.drawLine(int(px * 0.32), int(px * 0.42), int(px * 0.68), int(px * 0.42))
            p.drawLine(int(px * 0.32), int(px * 0.60), int(px * 0.56), int(px * 0.60))
        elif kind == "window":
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                int(px * 0.14), int(px * 0.18), int(px * 0.72), int(px * 0.64), 4, 4
            )
            p.drawLine(int(px * 0.16), int(px * 0.36), int(px * 0.84), int(px * 0.36))
        elif kind == "refresh":
            pen = QPen(
                col,
                2.1,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(px * 0.20, px * 0.20, px * 0.60, px * 0.60)
            p.drawArc(rect, 35 * 16, 285 * 16)
            p.drawLine(QPointF(px * 0.78, px * 0.20), QPointF(px * 0.78, px * 0.38))
            p.drawLine(QPointF(px * 0.78, px * 0.38), QPointF(px * 0.60, px * 0.38))
        elif kind == "nav_dot":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            s = int(px * 0.34)
            m = (px - s) // 2
            p.drawRoundedRect(m, m, s, s, 3, 3)
    finally:
        p.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)


def create_app_pixmap(size: int = 64) -> QPixmap:
    """
    SubVision düz geometrik Konsept A (Cinema Frame) logosunu HiDPI (2x) netliğinde yükler.
    """
    search_roots = [get_app_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    target_px = max(16, int(size) * 2)
    for root in search_roots:
        for fname in ("app_icon.png", "app_icon.ico"):
            icon_path = os.path.join(root, "assets", fname)
            if os.path.exists(icon_path):
                src_pix = QPixmap(icon_path)
                if not src_pix.isNull():
                    scaled = src_pix.scaled(
                        target_px,
                        target_px,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    rounded = QPixmap(target_px, target_px)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    try:
                        p.setRenderHint(QPainter.RenderHint.Antialiasing)
                        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        path = QPainterPath()
                        rad = target_px * 0.22
                        path.addRoundedRect(0.0, 0.0, float(target_px), float(target_px), rad, rad)
                        p.setClipPath(path)
                        p.drawPixmap(0, 0, scaled)
                    finally:
                        p.end()
                    rounded.setDevicePixelRatio(2.0)
                    return rounded

    # Procedural flat fallback matching assets/app_icon.svg (Concept A: Cinema Frame)
    pix = QPixmap(target_px, target_px)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = target_px / 512.0

        painter.setBrush(QColor("#111114"))
        painter.setPen(QPen(QColor("#27272E"), max(1.0, 6.0 * k)))
        painter.drawRoundedRect(
            QRectF(12 * k, 12 * k, 488 * k, 488 * k), 114 * k, 114 * k
        )

        bracket_pen = QPen(
            QColor("#FAFAFA"),
            max(1.8, 22.0 * k),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(bracket_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        def _corner(cx: float, cy: float, dx: int, dy: int) -> None:
            path = QPainterPath()
            path.moveTo(cx, cy + dy * 60.0 * k)
            path.lineTo(cx, cy + dy * 14.0 * k)
            path.quadTo(cx, cy, cx + dx * 14.0 * k, cy)
            path.lineTo(cx + dx * 68.0 * k, cy)
            painter.drawPath(path)

        _corner(98 * k, 124 * k, 1, 1)
        _corner(414 * k, 124 * k, -1, 1)
        _corner(98 * k, 388 * k, 1, -1)
        _corner(414 * k, 388 * k, -1, -1)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#52525B"))
        painter.drawRoundedRect(QRectF(170 * k, 236 * k, 172 * k, 24 * k), 12 * k, 12 * k)
        painter.setBrush(QColor("#F59E0B"))
        painter.drawRoundedRect(QRectF(142 * k, 284 * k, 228 * k, 34 * k), 17 * k, 17 * k)
    finally:
        painter.end()
    pix.setDevicePixelRatio(2.0)
    return pix


def create_app_icon() -> QIcon:
    search_roots = [get_app_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    for root in search_roots:
        for fname in ("app_icon.ico", "app_icon.png"):
            ico_path = os.path.join(root, "assets", fname)
            if os.path.exists(ico_path):
                return QIcon(ico_path)
    return QIcon(create_app_pixmap(64))


class ColorDotSwatch(QPushButton):
    """
    Studio 2.0 minimalist dairesel renk seçici (Figma Referans: halka çerçeveli renk noktası).
    """

    def __init__(self, hex_code: str, tooltip: str = "", parent: Optional[QWidget] = None):
        super().__init__("", parent)
        self.hex_code = hex_code
        self._selected = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            if self._selected:
                p.setPen(QPen(QColor("#FAFAFA"), 1.6))
            elif self.underMouse():
                p.setPen(QPen(QColor("#52525E"), 1.2))
            else:
                p.setPen(QPen(QColor("#2A2A32"), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 10.5, 10.5)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.hex_code))
            p.drawEllipse(QPointF(cx, cy), 6.2, 6.2)
        finally:
            p.end()


class SidebarNavButton(QPushButton):
    """
    Studio 2.0 sol kenar çubuğu (sidebar) navigasyon satırı.
    Sol küçük geometrik gösterge + başlık + opsiyonel sağ rozet (ör. CANLI veya sayı).
    """

    def __init__(self, label: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._label_text = label
        self._badge_text = ""
        self._badge_kind = "muted"  # 'muted' | 'live' | 'waiting'
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self.setText("")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(9)

        self._dot = QFrame(self)
        self._dot.setFixedSize(6, 6)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._dot)

        self._lbl = QLabel(label, self)
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._lbl, stretch=1)

        self._badge = QLabel("", self)
        self._badge.setFixedHeight(19)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._badge.hide()
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self._refresh_style()

    def set_nav_text(self, label: str) -> None:
        self._label_text = label
        self._lbl.setText(label)

    def setText(self, text: str) -> None:  # type: ignore[override]
        # Geriye dönük uyumluluk: main.py veya testler setText("Geçmiş (3)") çağırırsa ayrıştır
        clean = str(text or "").strip()
        if not clean:
            super().setText("")
            return
        if "(" in clean and clean.endswith(")"):
            base, rest = clean.rsplit("(", 1)
            self._lbl.setText(base.strip())
            self.set_badge(rest[:-1].strip(), kind="muted")
        else:
            self._lbl.setText(clean)
            if self._badge_kind == "muted":
                self.set_badge("", kind="muted")

    def text(self) -> str:  # type: ignore[override]
        if self._badge_text and self._badge_kind == "muted":
            return f"{self._lbl.text()} ({self._badge_text})"
        return self._lbl.text()

    def set_badge(self, text: str, kind: str = "muted") -> None:
        self._badge_text = str(text or "").strip()
        self._badge_kind = kind
        if not self._badge_text:
            self._badge.hide()
            return
        self._badge.setText(self._badge_text)
        if kind == "live":
            self._badge.setStyleSheet(
                "color: #22C55E; background-color: #132218; border: 1px solid #1E3A28; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        elif kind == "waiting":
            self._badge.setStyleSheet(
                "color: #F59E0B; background-color: #211B10; border: 1px solid #3D3117; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        else:
            self._badge.setStyleSheet(
                "color: #A1A1AA; background-color: #1B1B21; border: 1px solid #2A2A32; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        self._badge.show()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                "QPushButton { background-color: #1E1E24; border: 1px solid #2C2C35; border-radius: 7px; }"
            )
            self._dot.setStyleSheet("background-color: #F59E0B; border-radius: 2px; border: none;")
            self._lbl.setStyleSheet(
                "color: #FAFAFA; font-size: 9pt; font-weight: 600; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 7px; }"
                "QPushButton:hover { background-color: #18181D; }"
            )
            self._dot.setStyleSheet("background-color: #52525B; border-radius: 2px; border: none;")
            self._lbl.setStyleSheet(
                "color: #A1A1AA; font-size: 9pt; font-weight: 500; background: transparent; border: none;"
            )


class FlatSwitch(QCheckBox):
    """
    Modern monokrom flat toggle switch (QCheckBox uyumlu).
    Kapalı: koyu grafit kanal; Açık: yüksek kontrastlı düz beyaz kanal + koyu düğme.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(32 + 10 + text_w + 8, max(24, fm.height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            track_w, track_h = 32, 17
            y = (self.height() - track_h) // 2
            checked = self.isChecked()

            if checked:
                track_col = QColor("#FAFAFA")
                border_col = QColor("#FAFAFA")
                knob_col = QColor("#09090B")
            else:
                track_col = QColor("#24242B")
                border_col = QColor("#32323B")
                knob_col = QColor("#A1A1AA")

            p.setBrush(track_col)
            p.setPen(QPen(border_col, 1))
            p.drawRoundedRect(1, y, track_w, track_h, track_h / 2.0, track_h / 2.0)

            knob_d = 11
            knob_x = (track_w - knob_d - 2) if checked else 4
            knob_y = y + (track_h - knob_d) // 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(knob_col)
            p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

            p.setPen(QColor("#E4E4E7") if (self.isEnabled() and checked) else (QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B")))
            p.setFont(self.font())
            text_rect = QRect(track_w + 9, 0, self.width() - track_w - 9, self.height())
            p.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self.text(),
            )
        finally:
            p.end()


class FlatComboBox(QComboBox):
    """
    Sağ kenarında tüm platformlarda tutarlı, ince vektörel aşağı ok (chevron) çizen flat QComboBox.
    """

    def __init__(self, parent=None, on_before_popup=None):
        super().__init__(parent)
        self._on_before_popup = on_before_popup

    def showPopup(self) -> None:
        if callable(self._on_before_popup):
            try:
                self._on_before_popup()
            except Exception:
                pass
        super().showPopup()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B")
            pen = QPen(
                col,
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            cx = self.width() - 15
            cy = self.height() // 2
            p.drawLine(QPointF(cx - 3.6, cy - 1.8), QPointF(cx, cy + 2.0))
            p.drawLine(QPointF(cx, cy + 2.0), QPointF(cx + 3.6, cy - 1.8))
        finally:
            p.end()


class TelemetryCard(QFrame):
    """
    Studio 2.0 düz Performans Özeti Kartı (Ayarlar & Telemetri sekmesinde yer alır).
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
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 9px;
            }
            QFrame#telemetryCard QLabel {
                background-color: transparent;
                border: none;
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 11, 12, 11)
        lay.setSpacing(7)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #71717A; font-size: 7.3pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        hdr.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet(
            "color: #71717A; font-size: 7pt; font-weight: 600;"
        )
        hdr.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(hdr)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet(
            "color: #FAFAFA; font-size: 14.5pt; font-weight: 700; letter-spacing: -0.3px;"
        )
        lay.addWidget(self.lbl_val)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(max(4, min(100, int(initial_pct))))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(2)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                background-color: #24242A;
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
        self.lbl_sub.setStyleSheet("color: #71717A; font-size: 7.4pt; font-weight: 500;")
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
            self.bar.setValue(max(4, min(100, int(round(bar_pct)))))
