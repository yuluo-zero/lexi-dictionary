# -*- coding: utf-8 -*-
"""Always-on-top floating ball."""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from . import icons
from .theme import theme

SIZE = 62


class FloatingBall(QWidget):
    clicked = Signal()
    context_requested = Signal(QPoint)
    moved = Signal(QPoint)
    dock_changed = Signal(bool, str, int)

    SLIVER = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(SIZE + 22, SIZE + 22)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("划词查词 · 单击打开 · 拖动移动")
        self._hover = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_hover)
        self._press_pos: QPoint | None = None
        self._press_global: QPoint | None = None
        self._dragging = False
        self._opacity = 1.0
        self._docked = False
        self._expanded = False
        self._side = ""
        self._expanded_pos = QPoint(0, 0)
        self._badge = 0
        self._dock_timer = QTimer(self)
        self._dock_timer.setSingleShot(True)
        self._dock_timer.timeout.connect(self._collapse)
        self._move_anim: QPropertyAnimation | None = None

    def _get_hover(self):
        return self._hover

    def _set_hover(self, v):
        self._hover = float(v)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._docked and not self._expanded:
            self._paint_tab(p)
            self._paint_badge(p)
            return
        w = self.width()
        h = self.height()
        margin = 11
        rect = QRectF(margin - 2, margin - 1, w - 2 * margin + 4, h - 2 * margin + 4)
        scale = 1.0 + 0.05 * self._hover
        cx, cy = rect.center().x(), rect.center().y()
        r = rect.width() / 2 * scale

        # soft shadow
        for i in range(7):
            a = int(26 * (1 - i / 7) * (1.0 if theme.is_dark() else 0.9))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(30, 40, 70, a))
            p.drawEllipse(QRectF(cx - r - i * 1.6, cy - r - i * 1.6 + 4, (r + i * 1.6) * 2, (r + i * 1.6) * 2))

        grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        grad.setColorAt(0.0, QColor(theme["ball1"]))
        grad.setColorAt(1.0, QColor(theme["ball2"]))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # glossy top highlight
        gloss = QRadialGradient(cx - r * 0.25, cy - r * 0.55, r * 1.15)
        gloss.setColorAt(0.0, QColor(255, 255, 255, 70))
        gloss.setColorAt(0.55, QColor(255, 255, 255, 12))
        gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(gloss)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # inner ring
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.2))
        p.drawEllipse(QRectF(cx - r + 3, cy - r + 3, (r - 3) * 2, (r - 3) * 2))

        # icon
        icons.draw_icon(p, "book", QRectF(cx - 13, cy - 13, 26, 26), "#FFFFFF", 1.9)

        # hover dot
        if self._hover > 0.01:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(40 * self._hover)))
            p.drawEllipse(QRectF(cx - 11, cy - 11, 22, 22))
        self._paint_badge(p)

    def _paint_badge(self, p: QPainter):
        if self._badge <= 0:
            return
        if self.width() < 40:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E5484D"))
            p.drawEllipse(QRectF(self.width() / 2 - 4, 3, 8, 8))
            return
        text = "99+" if self._badge > 99 else str(self._badge)
        w = 20 if len(text) < 2 else 26
        x = self.width() - w - 3
        y = 3
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E5484D"))
        p.drawRoundedRect(QRectF(x, y, w, 18), 9, 9)
        p.setPen(QColor("#FFFFFF"))
        f = QFont("Segoe UI", 8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(x, y, w, 18), Qt.AlignCenter, text)

    def set_badge(self, count: int):
        count = max(0, int(count))
        if count != self._badge:
            self._badge = count
            self.update()

    def _paint_tab(self, p: QPainter):
        w, h = self.width(), self.height()
        tw = 14
        th = 52
        x = (w - tw) if self._side == "left" else 0
        y = (h - th) / 2
        grad = QLinearGradient(x, y, x + tw, y + th)
        grad.setColorAt(0.0, QColor(theme["ball1"]))
        grad.setColorAt(1.0, QColor(theme["ball2"]))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 30, 60, 26))
        p.drawRoundedRect(QRectF(x, y + 2, tw, th), 7, 7)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(x, y, tw, th), 7, 7)
        p.setBrush(QColor(255, 255, 255, 200))
        for i in (-6, 0, 6):
            p.drawRoundedRect(QRectF(x + tw / 2 - 3, y + th / 2 + i - 1, 6, 2.2), 1, 1)

    def enterEvent(self, e):
        if self._docked and not self._expanded:
            self._expand()
        self._dock_timer.stop()
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self.setCursor(Qt.OpenHandCursor)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._docked:
            self._dock_timer.start(700)
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(e)

    # ------------------------------------------------------------------ dock
    def _area(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _dock_xy(self):
        area = self._area()
        base_y = self._expanded_pos.y() if self._docked and self._expanded_pos.y() else self.y()
        y = max(area.top() + 4, min(base_y, area.bottom() - self.height() - 4))
        if self._side == "left":
            x = area.left() - (self.width() - self.SLIVER)
        else:
            x = area.right() - self.SLIVER
        return QPoint(x, y)

    def _expand(self):
        if not self._docked:
            return
        self._expanded = True
        self._move_to(self._expanded_pos)
        self.update()

    def _collapse(self):
        if not self._docked or self._dragging:
            return
        self._expanded = False
        self.update()
        self._move_to(self._dock_xy())

    def _move_to(self, pos: QPoint, duration: int = 220):
        if self._move_anim is not None:
            self._move_anim.stop()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(self.pos())
        anim.setEndValue(pos)
        anim.start()
        self._move_anim = anim

    def dock_at(self, side: str, y: int):
        self._side = "left" if side == "left" else "right"
        self._docked = True
        self._expanded = False
        area = self._area()
        y = max(area.top() + 4, min(int(y), area.bottom() - self.height() - 4))
        if self._side == "left":
            ex = area.left() + 4
        else:
            ex = area.right() - self.width() - 4
        self._expanded_pos = QPoint(ex, y)
        self.move(self._dock_xy())
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dock_timer.stop()
            self._docked = False
            self._expanded = False
            self._side = ""
            self._press_global = e.globalPosition().toPoint()
            self._press_pos = self.pos()
            self._dragging = False
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_global is None or not (e.buttons() & Qt.LeftButton):
            return
        delta = e.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() > 5:
            self._dragging = True
        if self._dragging:
            self.move(self._press_pos + delta)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setCursor(Qt.OpenHandCursor)
            if self._dragging:
                self._snap()
                self.moved.emit(self.pos())
            else:
                self.clicked.emit()
            self._press_global = None
            self._dragging = False
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        self.context_requested.emit(e.globalPos())
        e.accept()

    def _snap(self):
        area = self._area()
        x = self.x()
        y = self.y()
        near_left = x <= area.left() + 12
        near_right = x + self.width() >= area.right() - 12
        if near_left or near_right:
            self._side = "left" if near_left else "right"
            self._docked = True
            self._expanded = False
            y = max(area.top() + 4, min(y, area.bottom() - self.height() - 4))
            ex = area.left() + 4 if near_left else area.right() - self.width() - 4
            self._expanded_pos = QPoint(ex, y)
            self._move_to(self._dock_xy(), 200)
            self.update()
            self.moved.emit(self._expanded_pos)
            self.dock_changed.emit(True, self._side, y)
            return
        self._docked = False
        self._side = ""
        self.dock_changed.emit(False, "", y)
        if x - area.left() < 26:
            x = area.left() + 4
        elif area.right() - (x + self.width()) < 26:
            x = area.right() - self.width() - 4
        if y < area.top() - 4:
            y = area.top() + 4
        elif y + self.height() > area.bottom() + 8:
            y = area.bottom() - self.height() - 4
        if (x, y) != (self.x(), self.y()):
            self._move_to(QPoint(x, y), 180)
            self.moved.emit(QPoint(x, y))
        else:
            self.moved.emit(QPoint(x, y))

    def restore_position(self, pos):
        primary = QGuiApplication.primaryScreen()
        area = primary.availableGeometry()
        default_x = area.right() - self.width() - 24
        default_y = area.top() + int(area.height() * 0.42)
        if pos:
            try:
                x, y = int(pos[0]), int(pos[1])
            except (TypeError, ValueError, IndexError):
                x, y = default_x, default_y
            screen = QGuiApplication.screenAt(QPoint(x, y)) or primary
            area = screen.availableGeometry()
            # If the old position is outside this screen, fall back to the
            # comfortable default instead of leaving the ball half off-screen.
            if not (area.left() - 8 <= x <= area.right() - self.width() + 8
                    and area.top() - 8 <= y <= area.bottom() - self.height() + 8):
                x, y = default_x, default_y
        else:
            x, y = default_x, default_y
        self.move(
            max(area.left() + 4, min(x, area.right() - self.width() - 4)),
            max(area.top() + 4, min(y, area.bottom() - self.height() - 4)),
        )

    def reset_position(self):
        self._docked = False
        self._side = ""
        self._expanded = False
        self.restore_position(None)
