# -*- coding: utf-8 -*-
"""Application controller: wires the window, ball, bubble, tray and services."""
from __future__ import annotations

import logging
import html
import os
import threading
import time

from PySide6.QtCore import QObject, QPoint, QThreadPool, QRunnable, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, online
from . import config as config_module
from . import custom_format as custom_fmt
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
        self._selection_at = 0.0
        self._bubble_source = ""
        self._bubble_source_kind = ""
        self._bubble_pending_online = False
        self._bubble_online_fallback = False
        self._bubble_seq = 0
        self._bubble_online_signals = _BubbleOnlineSignals()
        self._bubble_online_signals.done.connect(self._on_bubble_online)
        self._bubble_expand_seq = 0
        self._bubble_expand_word = ""
        self._bubble_expand_signals = _BubbleExpandSignals()
        self._bubble_expand_signals.done.connect(self._on_bubble_expand)
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
        try:
            self.watcher.allow_hwnd = int(self.window.winId())
        except Exception:
            self.watcher.allow_hwnd = 0
        self.watcher.selection.connect(self._on_selection)
        self.watcher.clicked.connect(self._on_global_click)
        self.watcher.plain_click.connect(self._on_plain_click)
        self.watcher.key_pressed.connect(self._on_key_pressed)
        self.watcher.selection_blocked.connect(self._on_selection_blocked)
        if self.settings.get("selection_enabled", True):
            self.watcher.start()

        self.bubble.lookup_requested.connect(self.lookup_word)
        self.bubble.speak_requested.connect(lambda w: self.speak(w, self.settings.get("tts_accent", "us")))
        self.bubble.wordbook_requested.connect(self._bubble_wordbook)
        self.bubble.expand_requested.connect(self._expand_bubble)

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
        from PySide6.QtCore import QPoint

        point = QPoint(x, y)
        # Selections inside our own window are allowed only in the result
        # area.  Use the real foreground window: Qt's isActiveWindow() can
        # stay true while the user is clicking another app.
        own_foreground = False
        try:
            import ctypes
            own_foreground = (
                ctypes.windll.user32.GetForegroundWindow()
                == int(self.window.windowHandle().winId())
            )
        except Exception:
            own_foreground = self.window.isActiveWindow()
        if self.window.isVisible() and own_foreground and self.window.geometry().contains(point):
            page = self.window.search_page
            if not page.result_scroll.isVisible():
                log.info("selection skipped: own window, result area hidden")
                return
            if not page.result_scroll.rect().contains(
                page.result_scroll.mapFromGlobal(point)
            ):
                log.info("selection skipped: own window outside result area")
                return
        self._last_selection = text
        self._selection_at = time.time()

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
        source = ""
        self._bubble_source = ""
        self._bubble_source_kind = ""
        self._bubble_pending_online = False
        self._bubble_online_fallback = False
        kind = classify(text)
        try:
            if kind == "en":
                title, phonetic, brief, source, pending = self._bubble_payload(text)
                self._bubble_source = source
                self._bubble_pending_online = pending
            elif kind == "zh":
                entries = self.lexicon.lookup_chinese(text)
                if entries:
                    e = entries[0]
                    phonetic = e.get("pinyin", "")
                    brief = "；".join(e.get("glosses", [])[:2])[:90]
                    source = "CC-CEDICT · 离线"
                else:
                    brief = "点击查看英文翻译"
            else:
                brief = "点击翻译整句"
        except Exception:
            log.exception("bubble preview")
        if kind != "en":
            self._bubble_source = source
        if "有道" in self._bubble_source:
            self._bubble_source_kind = "youdao"
        elif "ECDICT" in self._bubble_source:
            self._bubble_source_kind = "ecdict"
        elif "WordNet" in self._bubble_source:
            self._bubble_source_kind = "wordnet"
        elif self._bubble_source.startswith("本地"):
            self._bubble_source_kind = "local"
        else:
            self._bubble_source_kind = ""
        self.marker.show_at(QPoint(x, y), text, text, phonetic, brief)

    def _bubble_payload(self, word: str):
        """Return (title, phonetic, brief, source, needs_online)."""
        pref = self.settings.get("bubble_source", "auto")
        local = []
        try:
            local = self.store.custom_lookup(word)
        except Exception:
            local = []

        def local_payload(item):
            data = custom_fmt.decode(item.get("definition", ""))
            if data:
                body = custom_fmt.preview_text(data, 1)
                phon = data.get("phon") or item.get("phonetic") or ""
            else:
                body = item.get("definition") or item.get("translation") or ""
                lines = [line.strip() for line in body.splitlines() if line.strip()]
                body = " ".join(lines[:3])[:180]
                phon = item.get("phonetic") or ""
            if not phon:
                try:
                    e, _ = self.lexicon.lookup_word(word)
                    phon = (e or {}).get("phonetic", "")
                except Exception:
                    pass
            src = "本地 · " + (item.get("source") or "词典")
            return word, phon, body, src, False

        def ecdict_payload():
            entry, _ = self.lexicon.lookup_word(word)
            if not entry:
                return None
            groups = entry.get("pos", {}).get("groups") or []
            brief = groups[0][2] if groups else (entry.get("translation") or "").split("\n")[0]
            return word, entry.get("phonetic", ""), brief[:180], "ECDICT · 离线", False

        def wordnet_payload():
            wn = self.lexicon.lookup_wordnet(word)
            if not wn:
                return None
            return word, "", wn[0].get("definition", "")[:180], "WordNet · 离线", False

        if pref.startswith("local:"):
            target = pref.split(":", 1)[1]
            matches = [x for x in local if (x.get("source") or "") == target]
            if matches:
                chosen = local_payload(matches[0])
            else:
                chosen = ecdict_payload() or wordnet_payload()
                if chosen:
                    chosen = chosen[:4] + (False,)
        elif pref == "local":
            chosen = local_payload(local[0]) if local else None
        elif pref == "ecdict":
            chosen = ecdict_payload()
        elif pref == "wordnet":
            chosen = wordnet_payload()
        elif pref == "youdao":
            chosen = ecdict_payload() or (local_payload(local[0]) if local else None)
            if chosen is None:
                chosen = (word, "", "正在查询在线释义…", "有道 · 在线", True)
            else:
                chosen = chosen[:4] + (True,)
        elif pref == "youdao_first":
            self._bubble_online_fallback = True
            chosen = (word, "", "正在查询在线释义…", "有道 · 在线", True)
        else:  # auto: local -> ECDICT -> WordNet
            chosen = (
                (local_payload(local[0]) if local else None)
                or ecdict_payload()
                or wordnet_payload()
            )

        if chosen is None:
            if self.settings.get("bubble_online_fallback", False):
                self._bubble_online_fallback = True
                return word, "", "正在查询在线释义…", "有道 · 在线", True
            return word, "", "本地词典未收录，点击查看详解", "", False

        # For a fixed online preference, keep the offline preview but fetch
        # the online definition in the background.
        if pref == "youdao":
            return chosen
        if self.settings.get("bubble_online_fallback", False):
            # Only fall back online when there is no offline hit.
            return chosen
        return chosen

    def _open_bubble_from_marker(self):
        m = self.marker
        if not m.query:
            return
        self.bubble.show_for(
            m.query, m.title, m.phonetic, m.brief, m.pos(), source=self._bubble_source,
            side=self.settings.get("bubble_side", "right"),
        )
        self.bubble.set_wordbook_state(self.store.has_word(m.query))
        if self._bubble_pending_online:
            self._start_bubble_online(m.query)
        m.hide_marker()

    def _start_bubble_online(self, word: str):
        self._bubble_seq += 1
        seq = self._bubble_seq
        job = _BubbleOnlineJob(word, seq, self._bubble_online_signals)
        QThreadPool.globalInstance().start(job)

    def _on_bubble_online(self, seq: int, word: str, data: dict):
        if seq != self._bubble_seq or self.bubble._word != word:
            return
        brief = ""
        if data:
            if data.get("cn"):
                brief = "；".join(data["cn"][:2])[:180]
            if not brief and data.get("en"):
                brief = data["en"][:180]
        if brief:
            self._bubble_online_fallback = False
            self._bubble_source_kind = "youdao"
            self.bubble.update_brief(brief, "有道 · 在线")
            return
        if self._bubble_online_fallback:
            self._bubble_online_fallback = False
            self._bubble_offline_fallback(word)

    def _bubble_offline_fallback(self, word: str):
        brief = ""
        source = ""
        try:
            entry, _ = self.lexicon.lookup_word(word)
            if entry:
                groups = entry.get("pos", {}).get("groups") or []
                brief = groups[0][2] if groups else (entry.get("translation") or "").split("\n")[0]
                source = "ECDICT · 离线（无网络）"
            if not brief:
                wn = self.lexicon.lookup_wordnet(word)
                if wn:
                    brief = wn[0].get("definition", "")
                    source = "WordNet · 离线（无网络）"
        except Exception:
            pass
        if brief:
            self._bubble_source_kind = "ecdict" if source.startswith("ECDICT") else "wordnet"
            self.bubble.update_brief(brief[:180], source)

    def _bubble_wordbook(self, word: str, phonetic: str, brief: str):
        word = (word or "").strip()
        if not word:
            return
        if self.store.has_word(word):
            self.store.remove_word(word)
            in_wordbook = False
        else:
            self.store.add_word(word, phonetic, brief)
            in_wordbook = True
        self.bubble.set_wordbook_state(in_wordbook)
        self.wordbook_changed.emit()

    def _ordered_source_keys(self):
        defaults = ["ecdict", "local", "wordnet", "collins", "youdao", "merriam"]
        raw = self.settings.get("source_order")
        order = [k for k in (raw if isinstance(raw, list) else []) if k in defaults]
        for key in defaults:
            if key not in order:
                order.append(key)
        return order

    def _ordered_bubble_keys(self):
        defaults = ["local", "ecdict", "wordnet", "youdao"]
        raw = self.settings.get("bubble_order")
        order = [k for k in (raw if isinstance(raw, list) else []) if k in defaults]
        for key in defaults:
            if key not in order:
                order.append(key)
        return order

    def _expand_bubble(self, word: str):
        word = (word or "").strip()
        if not word:
            return
        selected = self.settings.get("bubble_expand_sources")
        if not isinstance(selected, list):
            selected = ["local", "ecdict", "wordnet"]
        keys = [k for k in self._ordered_bubble_keys() if k in selected]
        # The compact card already shows one source; do not repeat that same
        # source again in the expanded body.
        if self._bubble_source_kind in ("youdao", "ecdict", "wordnet"):
            keys = [k for k in keys if k != self._bubble_source_kind]
        blocks = {}

        if "local" in keys:
            parts = []
            try:
                for item in self.store.custom_lookup(word)[:8]:
                    source = html.escape(item.get("source") or "本地")
                    parts.append(
                        '<p style="margin:8px 0 2px 0;color:#777"><b>%s</b></p>' % source
                    )
                    data = custom_fmt.decode(item.get("definition", ""))
                    if data:
                        parts.append(custom_fmt.to_html(data, expanded=True))
                    else:
                        body = item.get("definition") or item.get("translation") or ""
                        body = "\n".join(line for line in body.splitlines()[:12] if line.strip())
                        parts.append(
                            '<p style="margin:2px 0;white-space:pre-wrap">%s</p>'
                            % html.escape(body[:1600])
                        )
            except Exception:
                pass
            if parts:
                blocks["local"] = "".join(parts)

        if "ecdict" in keys:
            try:
                entry, _meta = self.lexicon.lookup_word(word)
                if entry:
                    lines = []
                    for _code, name, text in (entry.get("pos", {}).get("groups") or [])[:4]:
                        lines.append("<b>%s</b> %s" % (html.escape(name), html.escape(text)))
                    if lines:
                        blocks["ecdict"] = (
                            '<p style="margin:8px 0 2px 0;color:#777"><b>ECDICT</b></p>'
                            '<p style="margin:2px 0">%s</p>' % "<br>".join(lines)
                        )
            except Exception:
                pass

        if "wordnet" in keys:
            try:
                wn = self.lexicon.lookup_wordnet(word)
                if wn:
                    lines = [
                        html.escape(item.get("definition", ""))
                        for item in wn[:3] if item.get("definition")
                    ]
                    if lines:
                        blocks["wordnet"] = (
                            '<p style="margin:8px 0 2px 0;color:#777"><b>WordNet</b></p>'
                            '<p style="margin:2px 0">%s</p>' % "<br>".join(lines)
                        )
            except Exception:
                pass

        out = "".join(blocks[k] for k in keys if k in blocks)
        if "youdao" in keys and not out:
            out = '<p style="margin:8px 0;color:#777">有道 · 在线：查询中…</p>'
        self.bubble.set_details(out or "没有更多离线释义。")

        if "youdao" in keys:
            self._bubble_expand_seq += 1
            seq = self._bubble_expand_seq
            self._bubble_expand_word = word
            job = _BubbleExpandJob(word, seq, self._bubble_expand_signals)
            QThreadPool.globalInstance().start(job)

    def _on_bubble_expand(self, seq: int, word: str, data: dict):
        if seq != self._bubble_expand_seq or word != self._bubble_expand_word:
            return
        if not data or not self.bubble.isVisible() or self.bubble._word != word:
            return
        brief = ""
        if data.get("cn"):
            brief = "；".join(data["cn"][:3])
        elif data.get("en"):
            brief = data["en"]
        if not brief:
            return
        html_block = (
            '<p style="margin:8px 0 2px 0;color:#777"><b>有道 · 在线</b></p>'
            '<p style="margin:2px 0">%s</p>' % html.escape(brief[:1000])
        )
        self.bubble.append_details(html_block)

    def _on_key_pressed(self):
        if self.marker.isVisible():
            self.marker.hide_marker()

    def _on_plain_click(self):
        self.watcher.reset_dedupe()

    def _on_global_click(self, x: int, y: int):
        point = QPoint(x, y)
        if self.bubble.isVisible():
            if self.bubble.geometry().contains(point):
                return
            self.bubble.hide_animated()
        if not self.marker.isVisible():
            return
        if time.time() - self._selection_at < 0.35:
            # The watcher emits its click event around the same time as a new
            # double-click selection.  Do not let that event hide the marker
            # that was just created.
            return
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
class _BubbleExpandSignals(QObject):
    done = Signal(int, str, dict)


class _BubbleExpandJob(QRunnable):
    def __init__(self, word: str, seq: int, signals: _BubbleExpandSignals):
        super().__init__()
        self.word = word
        self.seq = seq
        self.signals = signals

    def run(self):
        try:
            data = online.youdao_lookup(self.word) or {}
        except Exception:
            data = {}
        try:
            self.signals.done.emit(self.seq, self.word, data)
        except RuntimeError:
            pass


class _BubbleOnlineSignals(QObject):
    done = Signal(int, str, dict)


class _BubbleOnlineJob(QRunnable):
    def __init__(self, word: str, seq: int, signals: _BubbleOnlineSignals):
        super().__init__()
        self.word = word
        self.seq = seq
        self.signals = signals

    def run(self):
        try:
            data = online.youdao_lookup(self.word) or {}
        except Exception:
            data = {}
        try:
            self.signals.done.emit(self.seq, self.word, data)
        except RuntimeError:
            pass


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
