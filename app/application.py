# -*- coding: utf-8 -*-
"""Application controller: wires the window, ball, bubble, tray and services."""
from __future__ import annotations

import logging
import os
import threading
import time

from PySide6.QtCore import QObject, QPoint, QThreadPool, QRunnable, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, online
from . import config as config_module
from .lexicon import Lexicon, has_cjk
from .search import SearchEngine, classify
from .selection import SelectionWatcher
from .store import Store
from .ui import icons
from .ui.ball import FloatingBall
from .ui.bubble import Bubble
from .ui.mainwindow import MainWindow
from .ui.marker import SelectionMarker
from .ui.quicksearch import QuickSearch
from .ui.theme import build_qss, set_theme, theme

log = logging.getLogger(__name__)


def _tray_icon() -> QIcon:
    ico = config.resource_path("assets", "app.ico")
    if os.path.exists(ico):
        return QIcon(ico)
    return icons.svg_icon("book", "#FFFFFF", 32)


class Application(QObject):
    wordbook_changed = Signal()
    settings_changed = Signal(str)

    def __init__(self, qapp: QApplication, start_hidden: bool = False):
        super().__init__()
        self.qapp = qapp
        self.version = config.VERSION
        self.config_module = config_module
        config.ensure_dirs()
        self.settings = config.load_settings()
        set_theme(self.settings.get("theme", "system"))
        qapp.setStyleSheet(build_qss(theme))

        self.store = Store(config.USER_DB)
        self.lexicon = Lexicon(config.DICT_DIR)
        self.engine = SearchEngine(self.lexicon, lambda: self.settings, store=self.store)

        self.window = MainWindow(self)
        self.bubble = Bubble()
        self.ball = FloatingBall()
        self.quick = QuickSearch()
        self.marker = SelectionMarker()
        self.marker.activated.connect(self._open_bubble_from_marker)
        self._suppress_same = False
        self._last_selection = ""
        self._blocked_notice_at = 0.0

        self._tray = QSystemTrayIcon(_tray_icon(), self)
        self._tray.setToolTip("划词词典")
        self._tray.setContextMenu(self._build_tray_menu())
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()
        self._tray_once = False

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.9)
        self._tts_signals = _TTSSignals(self)
        self._tts_signals.done.connect(self._on_tts)
        self._tts = None
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech

            self._tts = QTextToSpeech(self)
        except Exception:
            self._tts = None

        self.watcher = SelectionWatcher(lambda: self.settings)
        self.watcher.selection.connect(self._on_selection)
        self.watcher.clicked.connect(self._on_global_click)
        self.watcher.plain_click.connect(self._on_plain_click)
        self.watcher.key_pressed.connect(self._on_key_pressed)
        self.watcher.selection_blocked.connect(self._on_selection_blocked)
        if self.settings.get("selection_enabled", True):
            self.watcher.start()

        self.bubble.lookup_requested.connect(self.lookup_word)
        self.bubble.speak_requested.connect(lambda w: self.speak(w, self.settings.get("tts_accent", "us")))

        self.ball.clicked.connect(self._toggle_quick)
        self.quick.submitted.connect(self.lookup_word)
        self.ball.context_requested.connect(self._ball_menu)
        self.ball.moved.connect(lambda p: self.set_setting("ball_pos", [p.x(), p.y()], save=True))
        self.ball.dock_changed.connect(self._on_ball_dock)

        self._sync_autostart_flag()
        if self.settings.get("ball_enabled", True):
            if self.settings.get("ball_docked"):
                from PySide6.QtGui import QGuiApplication

                area = QGuiApplication.primaryScreen().availableGeometry()
                y = self.settings.get("ball_y")
                if y is None:
                    y = area.center().y() - self.ball.height() // 2
                elif y < area.top() + area.height() * 0.35 or y > area.top() + area.height() * 0.85:
                    # Old/default positions too close to the corners are
                    # uncomfortable; reset to the right-middle band.
                    y = area.top() + int(area.height() * 0.42)
                self.ball.dock_at(self.settings.get("ball_side", "right"), int(y))
            else:
                from PySide6.QtGui import QGuiApplication

                self.ball.restore_position(self.settings.get("ball_pos"))
                area = QGuiApplication.primaryScreen().availableGeometry()
                if self.ball.x() + self.ball.width() >= area.right() - 120:
                    self.ball.dock_at("right", self.ball.y())
                    self.settings["ball_docked"] = True
                    self.settings["ball_side"] = "right"
                    self.settings["ball_y"] = self.ball.y()
                elif self.ball.x() <= area.left() + 120:
                    self.ball.dock_at("left", self.ball.y())
                    self.settings["ball_docked"] = True
                    self.settings["ball_side"] = "left"
                    self.settings["ball_y"] = self.ball.y()
            self.ball.show()
            self.update_ball_badge()
            self._badge_timer = QTimer(self)
            self._badge_timer.setInterval(60000)
            self._badge_timer.timeout.connect(self.update_ball_badge)
            self._badge_timer.start()

        if self.settings.get("first_run", True):
            self.settings["first_run"] = False
            config.save_settings(self.settings)

        if not start_hidden:
            self.show_window()
            stats = self.lexicon.stats()
            if not stats["ready"]:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    self.window,
                    "离线词典缺失",
                    "没有找到离线词典数据：\n%s\n\n请确认 data\\dict 下的 ecdict.db、cedict.db、"
                    "wordnet.db 都在。在线查询仍可使用。" % config.DICT_DIR,
                )
        else:
            self._tray_notice("划词词典已在后台运行", "选中文字即可查词，悬浮球随时可以唤起窗口。")

    # ------------------------------------------------------------------ tray
    def _build_tray_menu(self) -> QMenu:
        menu = QMenu()
        act = menu.addAction("打开主窗口")
        act.triggered.connect(self.show_window)
        act2 = menu.addAction("查词")
        act2.triggered.connect(lambda: self.lookup_word(""))
        menu.addSeparator()
        self.tray_ball = menu.addAction("显示悬浮球")
        self.tray_ball.setCheckable(True)
        self.tray_ball.setChecked(bool(self.settings.get("ball_enabled", True)))
        self.tray_ball.triggered.connect(lambda v: self.set_setting("ball_enabled", v))
        self.tray_sel = menu.addAction("启用划词")
        self.tray_sel.setCheckable(True)
        self.tray_sel.setChecked(bool(self.settings.get("selection_enabled", True)))
        self.tray_sel.triggered.connect(lambda v: self.set_setting("selection_enabled", v))
        menu.addSeparator()
        menu.addAction("重置悬浮球位置").triggered.connect(self.reset_ball)
        due = self.store.due_count()
        review = menu.addAction("开始复习（%d）" % due)
        review.setEnabled(due > 0)
        review.triggered.connect(self.start_review)
        menu.addAction("设置").triggered.connect(self.show_settings)
        menu.addAction("退出").triggered.connect(self.quit)
        return menu

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible() and not self.window.isMinimized():
                self.window.hide()
            else:
                self.show_window()

    def _tray_notice(self, title: str, msg: str):
        try:
            self._tray.showMessage(title, msg, QSystemTrayIcon.Information, 3500)
        except Exception:
            pass

    def notify_tray_once(self):
        if not self._tray_once:
            self._tray_once = True
            self._tray_notice("划词词典还在后台", "悬浮球和划词继续工作；从托盘图标可以退出。")

    # ------------------------------------------------------------------ window
    def show_window(self):
        self.window.showNormal()
        self.window.ensure_on_screen()
        self.window.raise_()
        self.window.activateWindow()
        self.bubble.hide_animated()
        self.marker.hide_marker()

    def show_settings(self):
        self.show_window()
        self.window.show_page(3)

    def _toggle_quick(self):
        if self.quick.isVisible():
            self.quick.hide()
            return
        self.quick.show_near(self.ball.geometry().center(), self.ball.width())

    def _quick_submit(self, text: str):
        self.lookup_word(text)

    def start_review(self):
        self.show_window()
        self.window.show_page(1)
        self.window.wordbook_page.start_review()

    def update_ball_badge(self):
        try:
            self.ball.set_badge(self.store.due_count())
        except Exception:
            pass

    def lookup_word(self, text: str):
        started = time.perf_counter()
        self.show_window()
        QTimer.singleShot(120, self.window.bring_to_front)
        self.window.show_page(0)
        if text:
            self.window.search_page.search(text)
        else:
            self.window.search_page.focus_search()
        log.info("lookup %r window ready in %.0f ms", (text or "")[:24], (time.perf_counter() - started) * 1000)

    def note_lookup(self, res: dict):
        if not self.settings.get("history_enabled", True):
            return
        try:
            self.store.add_history(res.get("query", ""), res.get("kind", ""), res.get("brief", ""))
        except Exception:
            log.exception("history")
        if self.window.pages.currentIndex() == 2:
            self.window.history_page.refresh()

    # ------------------------------------------------------------------ selection
    def _on_selection_blocked(self, reason: str):
        now = time.time()
        if now - self._blocked_notice_at < 30:
            return
        self._blocked_notice_at = now
        if self._tray.isVisible():
            self._tray.showMessage("划词词典", reason, QSystemTrayIcon.Information, 3500)

    def _on_selection(self, text: str, x: int, y: int, double: bool = False):
        if not self.settings.get("selection_enabled", True):
            return
        text = text.strip()
        if not text:
            return
        self._last_selection = text
        from PySide6.QtCore import QPoint

        if len(text) > 60 or "\n" in text:
            title = text.replace("\n", " ")
            if len(title) > 26:
                title = title[:26] + "…"
            self.marker.show_at(
                QPoint(x, y), text, title, "", "选中的是一段文字，点开查看翻译"
            )
            return
        brief = ""
        phonetic = ""
        kind = classify(text)
        try:
            if kind == "en":
                entry, _meta = self.lexicon.lookup_word(text)
                if entry:
                    phonetic = entry.get("phonetic", "")
                    groups = entry.get("pos", {}).get("groups") or []
                    if groups:
                        brief = groups[0][2][:90]
                    elif entry.get("translation"):
                        brief = entry["translation"].split("\n")[0][:90]
                    else:
                        wn = self.lexicon.lookup_wordnet(text)
                        if wn:
                            brief = wn[0]["definition"][:90]
            elif kind == "zh":
                entries = self.lexicon.lookup_chinese(text)
                if entries:
                    e = entries[0]
                    phonetic = e.get("pinyin", "")
                    brief = "；".join(e.get("glosses", [])[:2])[:90]
                else:
                    brief = "点击查看英文翻译"
            else:
                brief = "点击翻译整句"
        except Exception:
            log.exception("bubble preview")
        self.marker.show_at(QPoint(x, y), text, text, phonetic, brief)

    def _open_bubble_from_marker(self):
        m = self.marker
        if not m.query:
            return
        self.bubble.show_for(m.query, m.title, m.phonetic, m.brief, m.pos())
        m.hide_marker()

    def _on_key_pressed(self):
        if self.marker.isVisible():
            self.marker.hide_marker()

    def _on_plain_click(self):
        self.watcher.reset_dedupe()

    def _on_global_click(self, x: int, y: int):
        if not self.marker.isVisible():
            return
        point = QPoint(x, y)
        if self.marker.geometry().contains(point):
            return
        if self.bubble.isVisible() and self.bubble.geometry().contains(point):
            return
        self.marker.hide_marker()

    # ------------------------------------------------------------------ speech
    def speak(self, text: str, accent: str | None = None):
        text = (text or "").strip()
        if not text:
            return
        accent = accent or self.settings.get("tts_accent", "us")
        # Chinese has a good local Windows voice; English uses the online
        # dictionary voice when available, then falls back to local TTS.
        if has_cjk(text):
            if self.settings.get("tts_system", True) and self._system_speak(text):
                return
        if self.settings.get("tts_online", True):
            cached = online.tts_cache_path(text, accent)
            if os.path.exists(cached) and os.path.getsize(cached) > 800:
                self._play(cached)
                return
            job = _TTSJob(text, accent, self._tts_signals)
            QThreadPool.globalInstance().start(job)
            return
        if self.settings.get("tts_system", True):
            self._system_speak(text)

    def _on_tts(self, path: str, text: str):
        if path:
            self._play(path)
        elif self.settings.get("tts_system", True):
            self._system_speak(text)

    def _play(self, path: str):
        log.info("tts play %s", os.path.basename(path))
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        QTimer.singleShot(700, lambda: log.info(
            "tts state=%s status=%s err=%s",
            self._player.playbackState(), self._player.mediaStatus(), self._player.errorString(),
        ))

    def _system_speak(self, text: str) -> bool:
        if not self._tts:
            return False
        try:
            from PySide6.QtCore import QLocale

            if not self._tts.availableVoices():
                return False
            locale = QLocale(QLocale.Chinese, QLocale.China) if has_cjk(text) else QLocale(QLocale.English, QLocale.UnitedStates)
            self._tts.setLocale(locale)
            self._tts.stop()
            self._tts.say(text)
            return True
        except Exception:
            log.exception("system tts")
            return False

    # ------------------------------------------------------------------ settings
    def set_setting(self, key: str, value, save: bool = True):
        if key == "theme":
            self.apply_theme(value)
            return
        self.settings[key] = value
        if save:
            config.save_settings(self.settings)
        if key == "ball_enabled":
            if value:
                self.ball.restore_position(self.settings.get("ball_pos"))
                self.ball.show()
            else:
                self.ball.hide()
            if hasattr(self, "tray_ball"):
                self.tray_ball.setChecked(bool(value))
        elif key == "selection_enabled":
            self.watcher.set_enabled(bool(value))
            if hasattr(self, "tray_sel"):
                self.tray_sel.setChecked(bool(value))
        elif key == "autostart":
            self.set_autostart(bool(value))
        self._sync_sidebar_switches()
        self.settings_changed.emit(key)

    def _sync_sidebar_switches(self):
        sb = getattr(self.window, "sidebar", None)
        if not sb:
            return
        for sw, key in ((sb.sel_switch, "selection_enabled"), (sb.ball_switch, "ball_enabled")):
            sw.blockSignals(True)
            sw.setChecked(bool(self.settings.get(key, True)))
            sw.blockSignals(False)

    def apply_theme(self, mode: str):
        self.settings["theme"] = mode
        config.save_settings(self.settings)
        set_theme(mode)
        self.window.apply_theme(mode)
        self.bubble.apply_theme()
        self.ball.update()
        self._tray.setIcon(_tray_icon())

    # ------------------------------------------------------------------ autostart
    def _sync_autostart_flag(self):
        active = self.autostart_active()
        if active != bool(self.settings.get("autostart", False)):
            self.settings["autostart"] = active

    def autostart_active(self) -> bool:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                try:
                    winreg.QueryValueEx(k, config.APP_NAME)
                    return True
                except FileNotFoundError:
                    return False
        except OSError:
            return False

    def set_autostart(self, enabled: bool):
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                winreg.KEY_SET_VALUE,
            )
            with key:
                if enabled:
                    winreg.SetValueEx(key, config.APP_NAME, 0, winreg.REG_SZ, config.startup_command())
                else:
                    try:
                        winreg.DeleteValue(key, config.APP_NAME)
                    except FileNotFoundError:
                        pass
            self.settings["autostart"] = enabled
            config.save_settings(self.settings)
            return True, ""
        except OSError as exc:
            log.exception("autostart")
            return False, "写入注册表失败：%s" % exc

    # ------------------------------------------------------------------ misc
    def open_data_dir(self):
        try:
            os.startfile(config.DATA_DIR)
        except OSError:
            log.exception("open data dir")

    def clear_tts_cache(self) -> int:
        return online.clear_tts_cache()

    def provider_label(self) -> str:
        return online.provider_name(self.settings.get("translate_provider", "mymemory"))

    def test_translate(self) -> str:
        res = online.translate("Hello, world. 今天天气真好。", self.settings)
        if not res:
            return "没有返回结果。"
        if res.get("error"):
            return "失败：" + res["error"]
        return "成功（%s）：\n%s" % (res.get("provider"), res.get("text", ""))

    def _on_ball_dock(self, docked: bool, side: str, y: int):
        self.settings["ball_docked"] = bool(docked)
        self.settings["ball_side"] = side or "right"
        self.settings["ball_y"] = int(y)
        config.save_settings(self.settings)

    def _ball_menu(self, pos):
        menu = QMenu()
        menu.addAction("快捷搜索").triggered.connect(self._toggle_quick)
        due = self.store.due_count()
        review = menu.addAction("开始复习（%d）" % due)
        review.setEnabled(due > 0)
        review.triggered.connect(self.start_review)
        menu.addAction("打开主窗口").triggered.connect(self.show_window)
        menu.addAction("设置").triggered.connect(self.show_settings)
        menu.addAction("重置悬浮球位置").triggered.connect(self.reset_ball)
        menu.addSeparator()
        hide = menu.addAction("隐藏悬浮球")
        hide.triggered.connect(lambda: self.set_setting("ball_enabled", False))
        menu.addAction("退出").triggered.connect(self.quit)
        menu.exec(pos)

    def reset_ball(self):
        from PySide6.QtGui import QGuiApplication

        area = QGuiApplication.primaryScreen().availableGeometry()
        y = area.top() + int(area.height() * 0.42)
        self.ball.dock_at("right", y)
        self.ball.show()
        self.settings["ball_docked"] = True
        self.settings["ball_side"] = "right"
        self.settings["ball_y"] = int(y)
        self.settings["ball_pos"] = [self.ball.x(), self.ball.y()]
        config.save_settings(self.settings)

    def quit(self):
        try:
            self.window.save_geometry()
        except Exception:
            pass
        self.watcher.stop()
        self.bubble.hide()
        self.ball.hide()
        self._tray.hide()
        config.save_settings(self.settings)
        self.qapp.quit()


# --------------------------------------------------------------------------- tts job
class _TTSSignals(QObject):
    done = Signal(str, str)


class _TTSJob(QRunnable):
    def __init__(self, text: str, accent: str, signals: _TTSSignals):
        super().__init__()
        self.text = text
        self.accent = accent
        self.signals = signals

    def run(self):
        path = None
        try:
            path = online.fetch_tts(self.text, self.accent)
        except Exception:
            path = None
        try:
            self.signals.done.emit(path or "", self.text)
        except RuntimeError:
            pass
