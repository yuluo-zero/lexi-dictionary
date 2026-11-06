# -*- coding: utf-8 -*-
"""The little card that appears next to a selection."""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from . import icons
from .theme import theme
from .widgets import IconButton, label


class Bubble(QWidget):
    lookup_requested = Signal(str)
    speak_requested = Signal(str)
    wordbook_requested = Signal(str, str, str)
    expand_requested = Signal(str)

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
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFixedWidth(344)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 18)

        self.card = QFrame(self)
        self.card.setObjectName("bubbleCard")
        self.card.setStyleSheet(
            f"QFrame#bubbleCard {{ background: {theme['bubble']}; border: 1px solid {theme['border']};"
            f" border-radius: 14px; }}"
        )
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 8)
        c = QColor(theme["shadow"])
        c.setAlpha(110 if theme.is_dark() else 60)
        shadow.setColor(c)
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(16, 13, 14, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.word_lb = QLabel(self.card)
        f = QFont("Georgia", 15)
        f.setWeight(QFont.DemiBold)
        self.word_lb.setFont(f)
        self.word_lb.setStyleSheet(f"color:{theme['text']};")
        top.addWidget(self.word_lb, 0, Qt.AlignVCenter)
        self.ph_lb = label("", "phonetic", self.card)
        top.addWidget(self.ph_lb, 0, Qt.AlignVCenter)
        top.addStretch(1)
        self.speak_btn = IconButton("volume", self.card, 15, "发音", box=28)
        self.speak_btn.clicked.connect(lambda: self.speak_requested.emit(self._word))
        top.addWidget(self.speak_btn)
        lay.addLayout(top)

        self.brief_lb = QLabel(self.card)
        self.brief_lb.setWordWrap(True)
        self.brief_lb.setStyleSheet(f"color:{theme['sub']}; font-size:13px;")
        lay.addWidget(self.brief_lb)

        self.source_lb = label("", "faint", self.card)
        self.source_lb.hide()
        lay.addWidget(self.source_lb)

        self.detail_lb = QLabel(self.card)
        self.detail_lb.setWordWrap(True)
        self.detail_lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_lb.setStyleSheet(f"color:{theme['sub']}; font-size:12px;")
        self.detail_lb.hide()
        lay.addWidget(self.detail_lb)

        divider = QFrame(self.card)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background:{theme['border']};")
        lay.addWidget(divider)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.book_btn = QPushButton("＋ 生词本", self.card)
        self.book_btn.setObjectName("chip")
        self.book_btn.setCursor(Qt.PointingHandCursor)
        self.book_btn.clicked.connect(self._wordbook_clicked)
        bottom.addWidget(self.book_btn)
        self.expand_btn = QPushButton("展开", self.card)
        self.expand_btn.setObjectName("chip")
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.clicked.connect(self._expand_clicked)
        bottom.addWidget(self.expand_btn)
        bottom.addStretch(1)
        self.open_btn = QLabel("查看详解  ›", self.card)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setStyleSheet(
            f"color:{theme['accent']}; font-size:12px; font-weight:600;"
        )
        self.open_btn.mousePressEvent = lambda e: self._open()  # type: ignore
        bottom.addWidget(self.open_btn)
        lay.addLayout(bottom)

        self._word = ""
        self._expanded = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_animated)
        self._anim: QPropertyAnimation | None = None
        self._pos_anim: QPropertyAnimation | None = None
        self._drag_origin: QPoint | None = None
        self._drag_pos: QPoint | None = None
        self._drag_moved = False
        self.card.setCursor(Qt.OpenHandCursor)
        for w in (self.card, self.word_lb, self.ph_lb, self.brief_lb, self.detail_lb):
            w.installEventFilter(self)

    # ------------------------------------------------------------------ drag
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._drag_origin = ev.globalPosition().toPoint()
            self._drag_pos = self.pos()
            self._drag_moved = False
            self._timer.stop()
            self.card.setCursor(Qt.ClosedHandCursor)
            return False
        if t == QEvent.MouseMove and self._drag_origin is not None and (ev.buttons() & Qt.LeftButton):
            delta = ev.globalPosition().toPoint() - self._drag_origin
            if not self._drag_moved and delta.manhattanLength() > 4:
                self._drag_moved = True
            if self._drag_moved:
                self.move(self._drag_pos + delta)
                return True
            return False
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
            self._drag_origin = None
            self.card.setCursor(Qt.OpenHandCursor)
            if not self._drag_moved:
                self._timer.start(5000)
            return False
        return super().eventFilter(obj, ev)

    def apply_theme(self):
        self.card.setStyleSheet(
            f"QFrame#bubbleCard {{ background: {theme['bubble']}; border: 1px solid {theme['border']};"
            f" border-radius: 14px; }}"
        )
        self.word_lb.setStyleSheet(f"color:{theme['text']};")
        self.brief_lb.setStyleSheet(f"color:{theme['sub']}; font-size:13px;")
        self.open_btn.setStyleSheet(f"color:{theme['accent']}; font-size:12px; font-weight:600;")
        self.speak_btn.refresh()

    def show_for(self, query: str, title: str, phonetic: str, brief: str, pos: QPoint,
                 source: str = ""):
        self._word = query
        self.word_lb.setText(title)
        f = QFont("Microsoft YaHei UI" if any("\u4e00" <= ch <= "\u9fff" for ch in title) else "Georgia", 15)
        f.setWeight(QFont.DemiBold)
        self.word_lb.setFont(f)
        self.ph_lb.setText(phonetic or "")
        self.ph_lb.setVisible(bool(phonetic))
        self.brief_lb.setText(brief or "（本地词典未收录，查看在线释义）")
        self.brief_lb.setVisible(True)
        self.source_lb.setText(source or "")
        self.source_lb.setVisible(bool(source))
        self._expanded = False
        self.detail_lb.clear()
        self.detail_lb.hide()
        self.expand_btn.setText("展开")
        self.setFixedWidth(344)
        self.apply_theme()
        self.adjustSize()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = pos.x() + 14
        y = pos.y() + 20
        if x + w > area.right() - 8:
            x = pos.x() - w - 14
        if y + h > area.bottom() - 8:
            y = pos.y() - h - 16
        x = max(area.left() + 8, min(x, area.right() - w - 8))
        y = max(area.top() + 8, min(y, area.bottom() - h - 8))
        self.move(x, y + 6)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._timer.start(int(settings_timeout() * 1000))
        self._fade(1.0)
        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(140)
        self._pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._pos_anim.setStartValue(QPoint(x, y + 6))
        self._pos_anim.setEndValue(QPoint(x, y))
        self._pos_anim.start()

    def _fade(self, target: float):
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(130)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(target)
        self._anim.start()

    def _open(self):
        if self._word:
            self.lookup_requested.emit(self._word)
        self.hide_animated()

    def _speak(self):
        if self._word:
            self.speak_requested.emit(self._word)

    def _wordbook_clicked(self):
        if self._word:
            self.wordbook_requested.emit(self._word, self.ph_lb.text(), self.brief_lb.text())

    def _expand_clicked(self):
        if self._expanded:
            self._set_expanded(False)
        elif self._word:
            self.expand_requested.emit(self._word)

    def set_wordbook_state(self, in_wordbook: bool):
        self.book_btn.setText("✓ 已在生词本" if in_wordbook else "＋ 生词本")

    def update_brief(self, brief: str, source: str = ""):
        self.brief_lb.setText(brief or "")
        self.source_lb.setText(source or "")
        self.source_lb.setVisible(bool(source))
        self.adjustSize()
        self._clamp_to_screen()

    def set_details(self, text: str):
        text = (text or "").strip()
        self.detail_lb.setText(text or "没有更多离线释义。")
        self._set_expanded(True)
        self._timer.stop()

    def _set_expanded(self, expanded: bool):
        self._expanded = bool(expanded)
        self.detail_lb.setVisible(self._expanded)
        self.expand_btn.setText("收起" if self._expanded else "展开")
        self.setFixedWidth(440 if self._expanded else 344)
        self.adjustSize()
        self._clamp_to_screen()
        if self._expanded:
            self._timer.stop()
        elif self.isVisible():
            self._timer.start(int(settings_timeout() * 1000))

    def _clamp_to_screen(self):
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = max(area.left() + 8, min(self.x(), area.right() - w - 8))
        y = max(area.top() + 8, min(self.y(), area.bottom() - h - 8))
        self.move(x, y)

    def enterEvent(self, e):
        self._timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._expanded:
            self._timer.start(2600)
        super().leaveEvent(e)

    def hide_animated(self):
        if not self.isVisible():
            return
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(110)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.hide)
        self._anim.start()


def settings_timeout() -> float:
    try:
        from .. import config

        return float(config.load_settings().get("bubble_timeout_s", 7) or 7)
    except Exception:
        return 7.0
