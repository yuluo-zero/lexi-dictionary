# -*- coding: utf-8 -*-
"""Small floating marker shown next to a text selection.

The full explanation card only opens after the marker is clicked, so ordinary
reading is not interrupted by a big popup.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import icons
from .theme import theme

SIZE = 32
BALL = 26


class SelectionMarker(QWidget):
    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(SIZE, SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点一下查词")
        self._hover = False
        self._press: QPoint | None = None
        self._origin: QPoint | None = None
        self._moved = False
        self._query = ""
        self._title = ""
        self._phonetic = ""
        self._brief = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)

    # ------------------------------------------------------------------ content
    def set_content(self, query: str, title: str, phonetic: str, brief: str):
        self._query = query
        self._title = title
        self._phonetic = phonetic
        self._brief = brief

    @property
    def query(self) -> str:
        return self._query

    @property
    def title(self) -> str:
        return self._title

    @property
    def phonetic(self) -> str:
        return self._phonetic

    @property
    def brief(self) -> str:
        return self._brief

    def show_at(self, pos: QPoint, query: str, title: str, phonetic: str, brief: str):
        self.set_content(query, title, phonetic, brief)
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = pos.x() + 4
        y = pos.y() + 8
        if x + self.width() > area.right() - 6:
            x = pos.x() - self.width() - 4
        if y + self.height() > area.bottom() - 6:
            y = pos.y() - self.height() - 6
        x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
        y = max(area.top() + 4, min(y, area.bottom() - self.height() - 4))
        self.move(x, y)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(120)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
    def hide_marker(self):
        self._timer.stop()
        self.hide()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r = BALL / 2
        # shadow
        for i in range(5):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 30, 60, 22 - i * 4))
            p.drawEllipse(QRectF(cx - r - i * 1.2, cy - r - i * 1.2 + 2, (r + i * 1.2) * 2, (r + i * 1.2) * 2))
        grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        grad.setColorAt(0.0, QColor(theme["ball1"]))
        grad.setColorAt(1.0, QColor(theme["ball2"]))
        p.setBrush(grad)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 70 if self._hover else 40), 1.2))
        p.drawEllipse(QRectF(cx - r + 2.5, cy - r + 2.5, (r - 2.5) * 2, (r - 2.5) * 2))
        icons.draw_icon(p, "book", QRectF(cx - 7, cy - 7, 14, 14), "#FFFFFF", 2.0)
        # small dot so it reads as an action, not a decoration
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawEllipse(QRectF(cx + 6, cy + 6, 2.5, 2.5))

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    # ------------------------------------------------------------------ drag / click
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._origin = self.pos()
            self._moved = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        delta = e.globalPosition().toPoint() - self._press
        if not self._moved and delta.manhattanLength() > 4:
            self._moved = True
        if self._moved:
            self.move(self._origin + delta)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            moved = self._moved
            self._press = None
            self._moved = False
            if not moved:
                self._timer.stop()
                self.activated.emit()
        super().mouseReleaseEvent(e)
