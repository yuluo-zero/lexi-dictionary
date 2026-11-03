# -*- coding: utf-8 -*-
"""Reusable custom widgets."""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
    Signal, Property,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLayout, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import icons
from .theme import theme


def label(text: str = "", role: str = "body", parent=None, wrap: bool = False) -> QLabel:
    lb = QLabel(text, parent)
    lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def hline(parent=None) -> QFrame:
    f = QFrame(parent)
    f.setObjectName("hline")
    f.setFixedHeight(1)
    return f


class ToggleSwitch(QAbstractButton):
    """Animated iOS-style switch."""

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 26)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self):
        return QSize(44, 26)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme
        rect = QRectF(1, 2, self.width() - 2, self.height() - 4)
        radius = rect.height() / 2
        off = QColor(t["borderStrong"])
        on = QColor(t["accent"])
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(rect, radius, radius)
        d = rect.height() - 6
        x = rect.left() + 3 + (rect.width() - d - 6) * self._pos
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, rect.top() + 3, d, d))


class IconButton(QPushButton):
    def __init__(self, icon_name: str, parent=None, size: int = 18, tip: str = "", role: str = "ghost", box: int = 34):
        super().__init__(parent)
        self._name = icon_name
        self._size = size
        self._role = role
        self.setObjectName(role)
        self.setFixedSize(box, box)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        if tip:
            self.setToolTip(tip)
        self.refresh()

    def refresh(self):
        color = theme["sub"] if self._role == "ghost" else theme["text"]
        self.setIcon(icons.svg_icon(self._name, color, self._size))

    def set_icon(self, name: str):
        self._name = name
        self.refresh()

    def enterEvent(self, e):
        self.setIcon(icons.svg_icon(self._name, theme["text"], self._size))
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.refresh()
        super().leaveEvent(e)


class Chip(QLabel):
    """Small rounded badge."""

    def __init__(self, text: str, fg: str = "accent", bg: str = "accentSoft", parent=None, font_size: int = 11):
        super().__init__(text, parent)
        self._fg = fg
        self._bg = bg
        self._fs = font_size
        self.setContentsMargins(0, 0, 0, 0)
        self.setAlignment(Qt.AlignCenter)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + 20, 24)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPixelSize(self._fs)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        rect = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme[self._bg]))
        p.drawRoundedRect(rect, 7, 7)
        p.setPen(QColor(theme[self._fg]))
        p.drawText(rect, Qt.AlignCenter, self.text())


class RangeBadge(QWidget):
    """Collins star rating + frequency label."""

    def __init__(self, stars: int = 0, parent=None):
        super().__init__(parent)
        self.stars = max(0, min(5, stars))
        self.setFixedHeight(20)
        self.setMinimumWidth(96)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = 0
        for i in range(5):
            color = theme["amber"] if i < self.stars else theme["borderStrong"]
            icons.draw_icon(p, "star", QRectF(x, 1, 15, 15), color, 1.4)
            x += 18


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, hspacing=8, vspacing=8):
        super().__init__(parent)
        self._items = []
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x + w > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._v
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


class NavButton(QAbstractButton):
    """Sidebar navigation item with an SVG icon, active pill and badge."""

    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        self._icon = icon_name
        self._text = text
        self._badge = 0
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_badge(self, n: int):
        self._badge = max(0, n)
        self.update()

    def sizeHint(self):
        return QSize(180, 42)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme["accentSoft"]))
            p.drawRoundedRect(r.adjusted(0, 1, 0, -1), 11, 11)
            p.setBrush(QColor(theme["accent"]))
            p.drawRoundedRect(QRectF(0, self.height() / 2 - 9, 3, 18), 1.5, 1.5)
        elif self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme["surface2"]))
            p.drawRoundedRect(r.adjusted(0, 1, 0, -1), 11, 11)

        color = theme["accent"] if self.isChecked() else theme["sub"]
        icons.draw_icon(p, self._icon, QRectF(14, (self.height() - 18) / 2, 18, 18), color, 1.9)
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold if self.isChecked() else QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(theme["accent"] if self.isChecked() else theme["text"]))
        p.drawText(QRectF(42, 0, self.width() - 80, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text)
        if self._badge:
            txt = str(self._badge)
            fm = QFontMetrics(f)
            w = max(20, fm.horizontalAdvance(txt) + 12)
            badge = QRectF(self.width() - w - 12, (self.height() - 20) / 2, w, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme["accent"] if self.isChecked() else theme["surface3"]))
            p.drawRoundedRect(badge, 10, 10)
            p.setPen(QColor("#FFFFFF" if self.isChecked() else theme["sub"]))
            p.drawText(badge, Qt.AlignCenter, txt)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class SearchBox(QLineEdit):
    textEdited2 = Signal(str)

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("search")
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(54)
        self.setClearButtonEnabled(False)
        self._icon = QLabel(self)
        self._icon.setPixmap(icons.svg_icon("search", theme["faint"], 20).pixmap(20, 20))
        self._icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._clear = IconButton("close", self, 14, "清空", box=26)
        self._clear.hide()
        self._clear.clicked.connect(self.clear_and_focus)
        self.textChanged.connect(lambda s: self._clear.setVisible(bool(s)))
        self.textChanged.connect(self.textEdited2)

    def clear_and_focus(self):
        self.clear()
        self.setFocus()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._icon.move(18, (self.height() - 20) // 2)
        self._clear.move(self.width() - 40, (self.height() - 26) // 2)
        self.setTextMargins(0, 0, 0, 0)

    def refresh_icons(self):
        self._icon.setPixmap(icons.svg_icon("search", theme["faint"], 20).pixmap(20, 20))
        self._clear.refresh()


class Card(QFrame):
    def __init__(self, parent=None, soft: bool = False):
        super().__init__(parent)
        self.setObjectName("softcard" if soft else "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(22, 20, 22, 20)
        self._layout.setSpacing(12)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, w):
        self._layout.addWidget(w)
        return w


class SectionHeader(QWidget):
    def __init__(self, title: str, parent=None, extra: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        dot = QLabel(self)
        dot.setFixedSize(6, 6)
        dot.setStyleSheet(f"background:{theme['accent']};border-radius:3px;")
        row.addWidget(dot)
        self._title = label(title, "section")
        row.addWidget(self._title)
        row.addStretch(1)
        if extra:
            row.addWidget(extra)


class _EmptyArt(QWidget):
    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self._icon = icon_name
        self.setFixedSize(96, 96)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, 96, 96)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme["accentSoft"]))
        p.drawRoundedRect(rect, 28, 28)
        p.setBrush(QColor(theme["accent"]))
        p.setOpacity(0.14)
        p.drawRoundedRect(QRectF(10, 10, 76, 76), 22, 22)
        p.setOpacity(1.0)
        icons.draw_icon(p, self._icon, QRectF(28, 28, 40, 40), theme["accent"], 1.7)


class EmptyState(QWidget):
    def __init__(self, title: str, subtitle: str, icon_name: str = "search", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 30, 0, 30)
        lay.setSpacing(16)
        lay.setAlignment(Qt.AlignCenter)
        art = _EmptyArt(icon_name, self)
        lay.addWidget(art, 0, Qt.AlignHCenter)
        t = label(title, "body")
        t.setAlignment(Qt.AlignCenter)
        f = t.font()
        f.setPixelSize(16)
        f.setWeight(QFont.DemiBold)
        t.setFont(f)
        lay.addWidget(t)
        s = label(subtitle, "faint", wrap=True)
        s.setAlignment(Qt.AlignCenter)
        s.setFixedWidth(430)
        lay.addWidget(s)


def add_shadow(widget: QWidget, blur: int = 40, y: int = 10, alpha: int = 40):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, y)
    c = QColor(theme["shadow"])
    c.setAlpha(alpha)
    eff.setColor(c)
    widget.setGraphicsEffect(eff)
    return eff


def clear_layout(layout: QLayout):
    """Remove every item immediately so nothing lingers on screen."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
