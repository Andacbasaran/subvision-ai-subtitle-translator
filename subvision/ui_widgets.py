"""
SubVision AI — Reusable HiDPI PyQt6 UI Widgets & Vector Icon Helpers.
Extracted from main.py to keep the main studio window modular and maintainable.
"""

import os
import sys
from typing import Optional

from PyQt6.QtCore import QPointF, QRect, QSize, Qt
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
    QVBoxLayout,
    QWidget,
)

from hardware import get_app_base_dir, get_ui_font_family


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
    """
    SubVision AI logosunu (assets/app_icon.png) HiDPI (2x) yumuşak köşeli olarak yükler.
    """
    search_roots = [get_app_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    for root in search_roots:
        for fname in ("app_icon.png", "app_icon.ico"):
            icon_path = os.path.join(root, "assets", fname)
            if os.path.exists(icon_path):
                src_pix = QPixmap(icon_path)
                if not src_pix.isNull():
                    target_px = size * 2
                    scaled = src_pix.scaled(
                        target_px,
                        target_px,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    rounded = QPixmap(target_px, target_px)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    path = QPainterPath()
                    rad = target_px * 0.22
                    path.addRoundedRect(0.0, 0.0, float(target_px), float(target_px), rad, rad)
                    p.setClipPath(path)
                    p.drawPixmap(0, 0, scaled)
                    p.end()
                    rounded.setDevicePixelRatio(2.0)
                    return rounded

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
        QPen(QColor("#38BDF8"), max(2, size // 16), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(int(size * 0.23), y1, int(size * 0.77), y1)
    painter.setPen(
        QPen(
            QColor("#FACC15"),
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
        for fname in ("app_icon.ico", "app_icon.png"):
            ico_path = os.path.join(root, "assets", fname)
            if os.path.exists(ico_path):
                return QIcon(ico_path)
    return QIcon(create_app_pixmap(64))


class FlatSwitch(QCheckBox):
    """
    Modern flat toggle switch (QCheckBox uyumlu).
    Standart checkbox yerine tüm işletim sistemlerinde net görünen vektörel anahtar çizer.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(26)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(36 + 12 + text_w + 10, max(26, fm.height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_w, track_h = 36, 19
        y = (self.height() - track_h) // 2
        checked = self.isChecked()

        track_col = QColor("#0284C7") if checked else QColor("#162033")
        border_col = QColor("#38BDF8") if checked else QColor("#293852")
        p.setBrush(track_col)
        p.setPen(QPen(border_col, 1))
        p.drawRoundedRect(1, y, track_w, track_h, track_h / 2.0, track_h / 2.0)

        knob_d = 13
        knob_x = (track_w - knob_d - 2) if checked else 4
        knob_y = y + (track_h - knob_d) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF") if checked else QColor("#94A3B8"))
        p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

        p.setPen(QColor("#E2E8F0") if self.isEnabled() else QColor("#475569"))
        p.setFont(self.font())
        text_rect = QRect(track_w + 10, 0, self.width() - track_w - 10, self.height())
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
        pen = QPen(
            QColor("#38BDF8"),
            1.7,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        p.setPen(pen)
        cx = self.width() - 16
        cy = self.height() // 2
        p.drawLine(QPointF(cx - 4.0, cy - 2.0), QPointF(cx, cy + 2.2))
        p.drawLine(QPointF(cx, cy + 2.2), QPointF(cx + 4.0, cy - 2.0))
        p.end()


class TelemetryCard(QFrame):
    """
    Sade Performans Özeti Kartı (Gelişmiş Ayarlar sekmesinde yer alır).
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
                background-color: #090E1A;
                border: 1px solid #1C283E;
                border-radius: 10px;
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #94A3B8; font-size: 7.6pt; font-weight: 700; letter-spacing: 0.5px;"
        )
        top_row.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet(
            """
            color: #38BDF8;
            background-color: #0F1D33;
            border: 1px solid #1E3A5F;
            border-radius: 4px;
            padding: 1px 6px;
            font-size: 7pt;
            font-weight: 700;
            """
        )
        top_row.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(top_row)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet("color: #F8FAFC; font-size: 14pt; font-weight: 700;")
        lay.addWidget(self.lbl_val)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(initial_pct)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: #162033;
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
        self.lbl_sub.setStyleSheet("color: #64748B; font-size: 7.8pt; font-weight: 500;")
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
