# -*- coding: utf-8 -*-
"""Frameless main window: sidebar, title bar and pages."""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import icons
from .ball import SIZE as BALL_SIZE
from .pages import HistoryPage, SearchPage, SettingsPage, WordbookPage
from .theme import theme
from .widgets import IconButton, NavButton, ToggleSwitch, label

WM_NCHITTEST = 0x0084
WM_NCCALCSIZE = 0x0083
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
HTCLIENT = 1
BORDER = 7


def _get_x(lparam):
    return ctypes.c_short(lparam & 0xFFFF).value


def _get_y(lparam):
    return ctypes.c_short((lparam >> 16) & 0xFFFF).value


class LogoMark(QWidget):
    def __init__(self, parent=None, size: int = 38):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self._size, self._size)
        grad = QLinearGradient(0, 0, self._size, self._size)
        grad.setColorAt(0, QColor(theme["ball1"]))
        grad.setColorAt(1, QColor(theme["ball2"]))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(r, self._size * 0.3, self._size * 0.3)
        icons.draw_icon(p, "book", QRectF(self._size * 0.24, self._size * 0.24, self._size * 0.52, self._size * 0.52), "#FFFFFF", 2.0)


class EdgeGrip(QWidget):
    """A thin invisible strip that starts a native resize when dragged."""

    def __init__(self, parent, edges, cursor):
        super().__init__(parent)
        self._edges = edges
        self.setCursor(cursor)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            wh = self.window().windowHandle()
            if wh is not None:
                wh.startSystemResize(self._edges)
        e.accept()


class TitleBar(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window
        self.setFixedHeight(46)
        self._press: QPoint | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 10, 0)
        lay.setSpacing(4)
        self.page_lb = label("查词", "faint")
        lay.addWidget(self.page_lb)
        lay.addStretch(1)

        self.theme_btn = IconButton("moon" if not theme.is_dark() else "sun", self, 17, "切换主题", box=34)
        self.theme_btn.clicked.connect(window.cycle_theme)
        lay.addWidget(self.theme_btn)
        self.min_btn = IconButton("minus", self, 16, "最小化", box=34)
        self.min_btn.clicked.connect(window.showMinimized)
        lay.addWidget(self.min_btn)
        self.max_btn = IconButton("maximize", self, 15, "最大化", box=34)
        self.max_btn.clicked.connect(window.toggle_max)
        lay.addWidget(self.max_btn)
        self.close_btn = IconButton("close", self, 16, "关闭", box=34)
        self.close_btn.clicked.connect(window.request_close)
        lay.addWidget(self.close_btn)

    def refresh_icons(self):
        for b in (self.theme_btn, self.min_btn, self.max_btn, self.close_btn):
            b.refresh()
        self.theme_btn.set_icon("sun" if theme.is_dark() else "moon")

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._press is not None and e.buttons() & Qt.LeftButton:
            if (e.globalPosition().toPoint() - self._press).manhattanLength() > 4:
                self._press = None
                wh = self.window.windowHandle()
                if wh:
                    wh.startSystemMove()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.window.toggle_max()
        super().mouseDoubleClickEvent(e)


class Sidebar(QWidget):
    def __init__(self, app, window: "MainWindow"):
        super().__init__()
        self.app = app
        self.window = window
        self.setObjectName("sidebar")
        self.setFixedWidth(214)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(6)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        self.logo = LogoMark(self, 38)
        logo_row.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = label("划词词典", "appname")
        names.addWidget(name)
        names.addWidget(label("LEXI DICTIONARY", "faint"))
        logo_row.addLayout(names)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)
        lay.addSpacing(22)

        self.nav = []
        for i, (icon, text) in enumerate((
            ("search", "查词"), ("star", "生词本"), ("clock", "历史"), ("settings", "设置")
        )):
            b = NavButton(icon, text, self)
            b.clicked.connect(lambda _=False, idx=i: self.window.show_page(idx))
            lay.addWidget(b)
            self.nav.append(b)
        lay.addStretch(1)

        # toggles
        box = QFrame(self)
        box.setObjectName("softcard")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(8)
        row1 = QHBoxLayout()
        row1.addWidget(label("划词气泡", "faint"))
        row1.addStretch(1)
        self.sel_switch = ToggleSwitch(box, bool(app.settings.get("selection_enabled", True)))
        self.sel_switch.toggled.connect(lambda v: app.set_setting("selection_enabled", v))
        row1.addWidget(self.sel_switch)
        bl.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(label("悬浮球", "faint"))
        row2.addStretch(1)
        self.ball_switch = ToggleSwitch(box, bool(app.settings.get("ball_enabled", True)))
        self.ball_switch.toggled.connect(lambda v: app.set_setting("ball_enabled", v))
        row2.addWidget(self.ball_switch)
        bl.addLayout(row2)
        lay.addWidget(box)
        lay.addSpacing(8)

        status = QHBoxLayout()
        dot = QLabel(self)
        dot.setFixedSize(6, 6)
        dot.setStyleSheet("background:%s;border-radius:3px;" % theme["green"])
        status.addWidget(dot)
        status.addWidget(label("离线词典已就绪", "faint"))
        status.addStretch(1)
        lay.addLayout(status)
        lay.addWidget(label("v" + app.version, "faint"))

    def refresh(self):
        for b in self.nav:
            b.update()
        self.logo.update()
        self.sel_switch.update()
        self.ball_switch.update()

    def set_current(self, index: int):
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)


class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("划词词典")
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint
            | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setMinimumSize(1000, 600)
        self._fit_to_screen()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.root = QWidget(self)
        self.root.setObjectName("root")
        outer.addWidget(self.root)

        root_lay = QHBoxLayout(self.root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.sidebar = Sidebar(app, self)
        root_lay.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.titlebar = TitleBar(self)
        right.addWidget(self.titlebar)

        self.pages = QStackedWidget()
        self.search_page = SearchPage(app)
        self.search_page.searched.connect(app.lookup_word)
        self.wordbook_page = WordbookPage(app)
        self.history_page = HistoryPage(app)
        self.settings_page = SettingsPage(app)
        for p in (self.search_page, self.wordbook_page, self.history_page, self.settings_page):
            self.pages.addWidget(p)
        right.addWidget(self.pages, 1)
        root_lay.addLayout(right, 1)

        self._grips: list[EdgeGrip] = []
        self._build_grips()

        self._page = 0
        app.wordbook_changed.connect(self.update_badges)
        self.show_page(0)
        self.update_badges()
        self.restore_geometry()

    def _build_grips(self):
        specs = [
            (Qt.LeftEdge, Qt.SizeHorCursor),
            (Qt.RightEdge, Qt.SizeHorCursor),
            (Qt.TopEdge, Qt.SizeVerCursor),
            (Qt.BottomEdge, Qt.SizeVerCursor),
            (Qt.LeftEdge | Qt.TopEdge, Qt.SizeFDiagCursor),
            (Qt.RightEdge | Qt.BottomEdge, Qt.SizeFDiagCursor),
            (Qt.RightEdge | Qt.TopEdge, Qt.SizeBDiagCursor),
            (Qt.LeftEdge | Qt.BottomEdge, Qt.SizeBDiagCursor),
        ]
        for edges, cursor in specs:
            grip = EdgeGrip(self, edges, cursor)
            grip.show()
            grip.raise_()
            self._grips.append(grip)
        self._layout_grips()

    def _layout_grips(self):
        if not getattr(self, "_grips", None):
            return
        maxed = self.isMaximized()
        w, h = self.width(), self.height()
        m = 0           # opaque window: resize right at the real edge
        g = 5           # thickness of the resize strip
        c = 8           # corner size
        rects = [
            (m, m + c, g, max(0, h - 2 * (m + c))),
            (w - m - g, m + c, g, max(0, h - 2 * (m + c))),
            (m + c, m, max(0, w - 2 * (m + c)), g),
            (m + c, h - m - g, max(0, w - 2 * (m + c)), g),
            (m, m, c, c),
            (w - m - c, h - m - c, c, c),
            (w - m - c, m, c, c),
            (m, h - m - c, c, c),
        ]
        for grip, rect in zip(self._grips, rects):
            if maxed:
                grip.hide()
            else:
                grip.show()
                grip.setGeometry(*rect)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_grips()

    def _fit_to_screen(self):

        screen = QGuiApplication.primaryScreen()
        if not screen:
            self.resize(1140, 770)
            return
        area = screen.availableGeometry()
        logging.getLogger(__name__).info(
            "screen=%s avail=%s dpr=%s", screen.geometry(), area, screen.devicePixelRatio()
        )
        w = max(1000, min(1160, int(area.width() * 0.9)))
        h = max(600, min(800, int(area.height() * 0.88)))
        self.resize(w, h)
        self.move(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2)

    # ------------------------------------------------------------------ pages
    def show_page(self, index: int):
        self.pages.setCurrentIndex(index)
        self.sidebar.set_current(index)
        titles = ["查词", "生词本", "历史", "设置"]
        self.titlebar.page_lb.setText(titles[index])
        self._page = index
        if index == 1:
            self.wordbook_page.refresh()
        elif index == 2:
            self.history_page.refresh()
        elif index == 3:
            self.refresh_settings()

    def open_search(self, text: str):
        self.show_page(0)
        if text:
            self.search_page.search(text)

    def update_badges(self):
        try:
            n = len(self.app.store.words())
        except Exception:
            n = 0
        self.sidebar.nav[1].set_badge(n)

    def refresh_settings(self):
        idx = 3
        old = self.settings_page
        self.settings_page = SettingsPage(self.app)
        self.pages.insertWidget(idx, self.settings_page)
        self.pages.removeWidget(old)
        old.deleteLater()
        self.pages.setCurrentIndex(idx)

    # ------------------------------------------------------------------ theme
    def apply_theme(self, mode: str | None = None):
        """Theme was already applied globally; refresh local widgets."""
        self.titlebar.refresh_icons()
        self.sidebar.refresh()
        self.search_page.search_box.refresh_icons()
        self.search_page.rerender()
        if hasattr(self.settings_page, "on_theme_changed"):
            self.settings_page.on_theme_changed()
        self.update()

    def cycle_theme(self):
        mode = self.app.settings.get("theme", "system")
        order = {"system": "light", "light": "dark", "dark": "system"}
        self.app.apply_theme(order.get(mode, "light"))

    # ------------------------------------------------------------------ window
    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(0, self._sync_max_state)

    def _sync_max_state(self):
        maxed = self.isMaximized()
        m = 0
        self.layout().setContentsMargins(m, m, m, m)
        self.root.setProperty("maximized", "true" if maxed else "false")
        self.root.style().unpolish(self.root)
        self.root.style().polish(self.root)
        self.titlebar.max_btn.set_icon("restore" if maxed else "maximize")
        self._layout_grips()
    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange:
            self._sync_max_state()

    def request_close(self):
        self.save_geometry()
        if self.app.settings.get("close_to_tray", True):
            self.hide()
            self.app.notify_tray_once()
        else:
            self.app.quit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.request_close()
        elif e.key() == Qt.Key_F and e.modifiers() & Qt.ControlModifier:
            self.show_page(0)
            self.search_page.focus_search()
        super().keyPressEvent(e)

    def restore_geometry(self):
        geo = self.app.settings.get("window_geometry")
        if geo and len(geo) == 4:
            from PySide6.QtGui import QGuiApplication

            x, y, w, h = [int(v) for v in geo]
            screen = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2)) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            w = min(max(900, w), area.width())
            h = min(max(580, h), area.height())
            x = min(max(area.left(), x), area.right() - w)
            y = min(max(area.top(), y), area.bottom() - h)
            self.setGeometry(x, y, w, h)

    def save_geometry(self):
        if not self.isMaximized():
            g = self.geometry()
            self.app.set_setting("window_geometry", [g.x(), g.y(), g.width(), g.height()])

    def bring_to_front(self):
        """Raise above other windows even when Windows blocks normal activation."""
        try:
            u = ctypes.WinDLL("user32", use_last_error=True)
            u.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            u.SetForegroundWindow.argtypes = [wintypes.HWND]
            hwnd = wintypes.HWND(int(self.winId()))
            flags = 0x0002 | 0x0001 | 0x0010  # NOMOVE | NOSIZE | NOACTIVATE
            u.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)
            u.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)
            u.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def ensure_on_screen(self):

        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        if self.isMaximized():
            return
        g = self.frameGeometry()
        if area.contains(g):
            return
        w = min(max(900, g.width()), area.width())
        h = min(max(580, g.height()), area.height())
        self.resize(w, h)
        self.move(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2)

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_first_show", True):
            self._first_show = False
            QTimer.singleShot(0, self._first_show_adjust)

    def _first_show_adjust(self):
        self.ensure_on_screen()
        self._sync_max_state()
        self._apply_native_frame()
        self._apply_dwm_corners()
        QTimer.singleShot(0, self._apply_native_frame)
        QTimer.singleShot(150, self._apply_native_frame)
        logging.getLogger(__name__).info(
            "shown geometry=%s screen=%s", self.geometry(), self.screen().availableGeometry() if self.screen() else None
        )

    def _apply_native_frame(self):
        """Opaque frameless window + WS_THICKFRAME gives native edges/shadow."""
        try:
            u = ctypes.WinDLL("user32", use_last_error=True)
            u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            u.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            hwnd = wintypes.HWND(int(self.winId()))
            style = u.GetWindowLongPtrW(hwnd, -16)
            u.SetWindowLongPtrW(hwnd, -16, style | 0x00040000 | 0x00020000 | 0x00010000 | 0x00080000)
            u.SetWindowPos(hwnd, wintypes.HWND(0), 0, 0, 0, 0, 0x0037)
            self._apply_dwm_corners()
            logging.getLogger(__name__).info(
                "native frame hwnd=%s style=%x -> %x",
                int(self.winId()), style, u.GetWindowLongPtrW(hwnd, -16),
            )
        except Exception:
            logging.getLogger(__name__).exception("native frame failed")

    def _apply_dwm_corners(self):
        try:
            dwm = ctypes.WinDLL("dwmapi")
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(
                wintypes.HWND(int(self.winId())), 33, ctypes.byref(pref), ctypes.sizeof(pref)
            )
        except Exception:
            pass

    def nativeEvent(self, event_type, message):
        # Frameless hit-testing is deliberately left to Qt. Custom WM_NCHITTEST
        # maths turned the whole window into a resize border on high-DPI
        # displays, which blocked clicks, typing and dragging.
        return super().nativeEvent(event_type, message)
