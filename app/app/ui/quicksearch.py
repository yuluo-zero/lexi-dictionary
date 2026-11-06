# -*- coding: utf-8 -*-
"""Small quick-search popup anchored to the floating ball."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from . import icons
from .theme import theme


class QuickSearch(QWidget):
    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(320, 56)

        shell = QFrame(self)
        shell.setObjectName("quickShell")
        shell.setGeometry(4, 4, 312, 48)
        lay = QHBoxLayout(shell)
        lay.setContentsMargins(12, 4, 10, 4)
        lay.setSpacing(7)

        icon = QLabel(shell)
        icon.setPixmap(icons.svg_icon("search", theme["sub"], 15).pixmap(15, 15))
        lay.addWidget(icon)

        self.edit = QLineEdit(shell)
        self.edit.setPlaceholderText("便捷搜索：单词 / 中文 / 句子")
        self.edit.setFrame(False)
        self.edit.returnPressed.connect(self._submit)
        lay.addWidget(self.edit, 1)

        hint = QLabel("Enter", shell)
        hint.setObjectName("quickHint")
        lay.addWidget(hint)
        self.refresh_theme()

    def refresh_theme(self):
        self.setStyleSheet(
            f"QFrame#quickShell{{background:{theme['surface']};border:1px solid {theme['border']};"
            f"border-radius:12px;}}"
            f"QLineEdit{{background:transparent;border:none;color:{theme['text']};font-size:13px;}}"
            f"QLabel#quickHint{{color:{theme['faint']};font-size:10px;"
            f"border:1px solid {theme['border']};border-radius:5px;padding:1px 4px;}}"
        )

    def show_near(self, anchor: QPoint, ball_width: int = 0):
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if anchor.x() > area.center().x():
            x = anchor.x() - self.width() - 14
        else:
            x = anchor.x() + ball_width + 14
        y = anchor.y() - self.height() // 2
        x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
        y = max(area.top() + 8, min(y, area.bottom() - self.height() - 8))
        self.move(x, y)
        self.edit.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def _submit(self):
        text = self.edit.text().strip()
        if not text:
            return
        self.hide()
        self.submitted.emit(text)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(4, 4, 312, 48), 12, 12)
        p.fillPath(path, QColor(theme["surface"]))
