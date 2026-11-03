# -*- coding: utf-8 -*-
"""Colour tokens and the application stylesheet."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication


LIGHT = {
    "mode": "light",
    "bg": "#F3F4F7",
    "bg2": "#ECEEF3",
    "surface": "#FFFFFF",
    "surface2": "#F8F9FB",
    "surface3": "#EFF2F7",
    "border": "#E5E8EF",
    "borderStrong": "#D5DAE4",
    "text": "#161A22",
    "sub": "#5F6878",
    "faint": "#98A0AF",
    "accent": "#3B6BF0",
    "accentHover": "#2F5CDE",
    "accentSoft": "#EDF2FF",
    "accentText": "#FFFFFF",
    "green": "#0F9D58",
    "greenSoft": "#E9F8F0",
    "amber": "#D97706",
    "amberSoft": "#FEF4E6",
    "red": "#E5484D",
    "redSoft": "#FDECED",
    "purple": "#7C5CF5",
    "purpleSoft": "#F2EEFE",
    "shadow": "#1A2030",
    "bubble": "#FFFFFF",
    "ball1": "#4C7CF6",
    "ball2": "#7C5CF5",
    "scroll": "#C9CFDB",
    "scrollHover": "#AEB6C5",
    "overlay": "#0B0E14",
}

DARK = {
    "mode": "dark",
    "bg": "#0D0F14",
    "bg2": "#12151B",
    "surface": "#171A21",
    "surface2": "#1C2029",
    "surface3": "#232833",
    "border": "#262B36",
    "borderStrong": "#333A48",
    "text": "#EDEFF5",
    "sub": "#9AA2B1",
    "faint": "#6C7484",
    "accent": "#6E8DFF",
    "accentHover": "#849EFF",
    "accentSoft": "#1B2440",
    "accentText": "#0B1020",
    "green": "#3DDC97",
    "greenSoft": "#13291F",
    "amber": "#F5B44B",
    "amberSoft": "#2A2213",
    "red": "#FF6B6B",
    "redSoft": "#2C1618",
    "purple": "#A78BFA",
    "purpleSoft": "#221C36",
    "shadow": "#000000",
    "bubble": "#1B1F28",
    "ball1": "#5C86FF",
    "ball2": "#9B7BFF",
    "scroll": "#39404E",
    "scrollHover": "#4A5364",
    "overlay": "#000000",
}


class Theme:
    def __init__(self, colors: dict):
        self.colors = colors
        self.mode = colors["mode"]

    def __getitem__(self, key: str) -> str:
        return self.colors[key]

    def qcolor(self, key: str, alpha: int | None = None) -> QColor:
        c = QColor(self.colors[key])
        if alpha is not None:
            c.setAlpha(alpha)
        return c

    def is_dark(self) -> bool:
        return self.mode == "dark"


theme = Theme(LIGHT)


def resolve_mode(mode: str) -> str:
    if mode in ("light", "dark"):
        return mode
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"
    except Exception:
        return "light"


def set_theme(mode: str):
    """Mutate the shared Theme object so every module sees the new colours."""
    resolved = resolve_mode(mode)
    theme.colors = dict(DARK if resolved == "dark" else LIGHT)
    theme.mode = resolved
    app = QGuiApplication.instance()
    if app is not None:
        app.setStyleSheet(build_qss(theme))


def build_qss(t: Theme) -> str:
    c = t.colors
    return f"""
    * {{
        outline: none;
    }}
    QWidget {{
        color: {c['text']};
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QWidget#root {{
        background: {c['bg']};
        border: 1px solid {c['border']};
        border-radius: 0px;
    }}
    QWidget#root[maximized="true"] {{
        border-radius: 0px;
    }}
    QWidget#sidebar {{
        background: {c['surface']};
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-right: 1px solid {c['border']};
    }}
    QFrame#card, QWidget#card {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 16px;
    }}
    QFrame#softcard {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel[role="appname"] {{
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    QLabel[role="word"] {{
        font-family: "Georgia", "Cambria", serif;
        font-size: 38px;
        font-weight: 600;
        color: {c['text']};
    }}
    QLabel[role="phonetic"] {{
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 14px;
        color: {c['sub']};
    }}
    QLabel[role="section"] {{
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1.4px;
        color: {c['faint']};
    }}
    QLabel[role="sub"] {{
        color: {c['sub']};
    }}
    QLabel[role="faint"] {{
        color: {c['faint']};
        font-size: 12px;
    }}
    QLabel[role="body"] {{
        font-size: 13.5px;
        color: {c['text']};
    }}
    QLabel[role="def"] {{
        font-size: 14px;
        color: {c['text']};
        line-height: 150%;
    }}
    QLabel[role="en"] {{
        font-family: "Georgia", "Cambria", serif;
        font-size: 14px;
        color: {c['text']};
    }}
    QLabel[role="example"] {{
        font-family: "Georgia", "Cambria", serif;
        font-size: 12.5px;
        color: {c['sub']};
    }}
    QLabel[role="error"] {{
        color: {c['red']};
    }}
    QLabel[role="ok"] {{
        color: {c['green']};
    }}
    QLineEdit {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 9px 12px;
        selection-background-color: {c['accent']};
        selection-color: {c['accentText']};
    }}
    QLineEdit:focus {{
        background: {c['surface']};
        border: 1px solid {c['accent']};
    }}
    QLineEdit#search {{
        font-size: 15px;
        padding-left: 46px;
        padding-right: 96px;
        border-radius: 16px;
        background: {c['surface']};
        border: 1px solid {c['border']};
    }}
    QLineEdit#search:focus {{
        border: 1px solid {c['accent']};
        background: {c['surface']};
    }}
    QPushButton {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 6px 12px;
        color: {c['text']};
    }}
    QPushButton:hover {{
        background: {c['surface3']};
        border-color: {c['borderStrong']};
    }}
    QPushButton:pressed {{
        background: {c['border']};
    }}
    QPushButton#primary {{
        background: {c['accent']};
        color: {c['accentText']};
        border: none;
        font-weight: 600;
        padding: 8px 18px;
        border-radius: 10px;
    }}
    QPushButton#primary:hover {{
        background: {c['accentHover']};
    }}
    QPushButton#ghost {{
        background: transparent;
        border: 1px solid transparent;
        color: {c['sub']};
    }}
    QPushButton#ghost:hover {{
        background: {c['surface2']};
        color: {c['text']};
    }}
    QPushButton#wordlink {{
        background: transparent;
        border: none;
        padding: 0px;
        text-align: left;
        color: {c['text']};
    }}
    QPushButton#wordlink:hover {{
        color: {c['accent']};
    }}
    QPushButton#rowitem {{
        background: transparent;
        border: none;
        padding: 0px;
        text-align: left;
    }}
    QPushButton#rowitem:hover {{
        background: {c['surface2']};
        border-radius: 10px;
    }}
    QPushButton#chip {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 14px;
        padding: 5px 12px;
        color: {c['sub']};
        font-size: 12px;
    }}
    QPushButton#chip:hover {{
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    QPushButton#danger {{
        background: transparent;
        border: 1px solid {c['border']};
        color: {c['red']};
    }}
    QPushButton#danger:hover {{
        background: {c['redSoft']};
        border-color: {c['red']};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 2px 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['scroll']};
        border-radius: 4px;
        min-height: 36px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c['scrollHover']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        height: 0px;
    }}
    QComboBox {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 7px 12px;
        min-width: 120px;
    }}
    QComboBox:hover {{
        border-color: {c['borderStrong']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 6px;
        selection-background-color: {c['accentSoft']};
        selection-color: {c['text']};
        outline: none;
    }}
    QMenu {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 28px 8px 12px;
        border-radius: 8px;
        color: {c['text']};
    }}
    QMenu::item:selected {{
        background: {c['accentSoft']};
        color: {c['accent']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: 5px 8px;
    }}
    QToolTip {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 6px 9px;
        font-size: 12px;
    }}
    QTextEdit {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 8px;
    }}
    QCheckBox {{
        spacing: 8px;
        color: {c['text']};
    }}
    QFrame#hline {{
        background: {c['border']};
        max-height: 1px;
        border: none;
    }}
    """
