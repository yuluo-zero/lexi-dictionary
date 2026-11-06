# -*- coding: utf-8 -*-
"""The four pages inside the main window."""
from __future__ import annotations

import os
import re
import time

from PySide6.QtCore import QEvent, QObject, QRectF, QRunnable, QSize, QStringListModel, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QCompleter, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QInputDialog, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

from . import icons
from .. import custom_format as custom_fmt
from ..custom_dict import parse_custom_dictionary
from .theme import theme
from .widgets import (
    Card, Chip, EmptyState, FlowLayout, IconButton, RangeBadge, SearchBox,
    ToggleSwitch, clear_layout, hline, label,
)

TAG_COLORS = [
    ("accent", "accentSoft"), ("purple", "purpleSoft"), ("green", "greenSoft"),
    ("amber", "amberSoft"),
]

EXAM_NAMES = {
    "zk": "中考", "gk": "高考", "cet4": "四级", "cet6": "六级",
    "ky": "考研", "toefl": "托福", "ielts": "雅思", "gre": "GRE",
}


class _FulltextSignals(QObject):
    done = Signal(int, str, list)


class _FulltextJob(QRunnable):
    def __init__(self, token: int, text: str, lexicon, signals: _FulltextSignals, store=None):
        super().__init__()
        self.token = token
        self.text = text
        self.lexicon = lexicon
        self.signals = signals
        self.store = store

    def run(self):
        try:
            data = self.lexicon.fulltext_search(self.text)
        except Exception:
            data = []
        if self.store is not None:
            try:
                data = list(data) + self.store.custom_fulltext(self.text)
            except Exception:
                pass
        try:
            self.signals.done.emit(self.token, self.text, data)
        except RuntimeError:
            pass


def scroll_page() -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(30, 24, 30, 30)
    lay.setSpacing(16)
    area.setWidget(inner)
    return area, inner, lay


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(4)
        t = label(title, "body")
        f = t.font()
        f.setPixelSize(22)
        f.setWeight(QFont.DemiBold)
        t.setFont(f)
        lay.addWidget(t)
        if subtitle:
            lay.addWidget(label(subtitle, "faint"))


def section_card(title: str, parent=None, extra: QWidget | None = None) -> Card:
    card = Card(parent)
    head = QHBoxLayout()
    head.setSpacing(8)
    dot = QLabel(card)
    dot.setFixedSize(6, 6)
    dot.setStyleSheet(f"background:{theme['accent']};border-radius:3px;")
    head.addWidget(dot)
    head.addWidget(label(title, "section"))
    head.addStretch(1)
    if extra:
        head.addWidget(extra)
    card.body().addLayout(head)
    return card


def clickable_chip(text: str, on_click, fg="accent", bg="accentSoft") -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("chip")
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(lambda: on_click(text))
    return btn


# =========================================================================== search
class SearchPage(QWidget):
    searched = Signal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.settings = app.settings
        self.result = None
        self.online_data = None
        self.view_source = "all"
        self._local_open = set()
        self._example_open = set()
        self._linked_offset = 0
        self._syncing_scroll = False
        self._back_stack = []
        self.fulltext_results = []
        self.ft_token = 0
        self.ft_signals = _FulltextSignals(self)
        self.ft_signals.done.connect(self._on_fulltext)
        self._build()
        self._completer_model = QStringListModel(self)
        self._completer = QCompleter(self._completer_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchStartsWith)
        self._completer.setMaxVisibleItems(8)
        self.search_box.setCompleter(self._completer)
        self.search_box.textEdited.connect(self._update_completions)
        app.engine.local_ready.connect(self._on_local)
        app.engine.online_ready.connect(self._on_online)

    # ------------------------------------------------------------------ build
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 22, 30, 18)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.title = label("查词", "body")
        f = self.title.font()
        f.setPixelSize(22)
        f.setWeight(QFont.DemiBold)
        self.title.setFont(f)
        head.addWidget(self.title)
        head.addWidget(label("单词 · 短语 · 整句翻译", "faint"))
        head.addStretch(1)
        self.back_btn = QPushButton("← 返回")
        self.back_btn.setObjectName("chip")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.hide()
        head.addWidget(self.back_btn)
        self.mode_hint = label("中英互译 开 · 英英互译 开", "faint")
        head.addWidget(self.mode_hint)
        outer.addLayout(head)

        self.search_box = SearchBox("输入单词、中文或整句，回车查询…")
        self.search_box.returnPressed.connect(self._submit)
        self.search_box.textEdited2.connect(self._on_typing)
        outer.addWidget(self.search_box)

        self.chips_row = QWidget()
        chips = QHBoxLayout(self.chips_row)
        chips.setContentsMargins(2, 0, 0, 0)
        chips.setSpacing(8)
        chips.addWidget(label("试试", "faint"))
        for word in ("serendipity", "苹果", "take off", "今天天气真好"):
            b = QPushButton(word)
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, w=word: self.external_search(w))
            chips.addWidget(b)
        chips.addStretch(1)
        outer.addWidget(self.chips_row)

        self.stack_host = QWidget()
        self.stack_layout = QVBoxLayout(self.stack_host)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        self.stack_layout.setSpacing(0)
        outer.addWidget(self.stack_host, 1)

        self.empty = EmptyState(
            "选中文字，点小标志查词",
            "在浏览器、Word、PDF 里划选任意文字，旁边会冒出一个小标志；\n点它才打开释义，不点就不会打扰你。也可以直接在上方输入。",
            "book",
        )
        self.stack_layout.addWidget(self.empty, 1)

        self.result_page = QWidget()
        page_layout = QVBoxLayout(self.result_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)
        self.header_host = QWidget()
        self.header_layout = QVBoxLayout(self.header_host)
        self.header_layout.setContentsMargins(0, 4, 6, 0)
        self.header_layout.setSpacing(8)
        page_layout.addWidget(self.header_host)

        self.result_area = QWidget()
        result_row = QHBoxLayout(self.result_area)
        result_row.setContentsMargins(0, 0, 0, 0)
        result_row.setSpacing(14)

        self.result_scroll = QScrollArea()
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.result_inner = QWidget()
        self.result_layout = QVBoxLayout(self.result_inner)
        self.result_layout.setContentsMargins(0, 4, 6, 20)
        self.result_layout.setSpacing(14)
        self.result_scroll.setWidget(self.result_inner)
        self.result_scroll.verticalScrollBar().valueChanged.connect(self._on_left_scroll)
        result_row.addWidget(self.result_scroll, 1)

        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.right_scroll.setFixedWidth(300)
        self.right_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.right_inner = QWidget()
        self.right_layout = QVBoxLayout(self.right_inner)
        self.right_layout.setContentsMargins(0, 4, 6, 20)
        self.right_layout.setSpacing(14)
        self.right_scroll.setWidget(self.right_inner)
        self._apply_right_style()
        self.right_scroll.hide()
        result_row.addWidget(self.right_scroll, 0)
        page_layout.addWidget(self.result_area, 1)
        self.result_page.hide()
        self.stack_layout.addWidget(self.result_page, 1)
        self._back_shortcut = QShortcut(QKeySequence("Alt+Left"), self)
        self._back_shortcut.activated.connect(self.go_back)
        QApplication.instance().installEventFilter(self)

        self.status = label("", "faint")
        outer.addWidget(self.status)

    # ------------------------------------------------------------------ searching
    def _apply_right_style(self):
        transparent = bool(self.settings.get("right_transparent", True))
        background = "transparent" if transparent else theme["surface"]
        self.right_scroll.setStyleSheet(
            f"QScrollArea{{background:{background};border:none;}}"
            f"QScrollBar:vertical{{width:5px;background:transparent;margin:0;}}"
            f"QScrollBar::handle:vertical{{background:{theme['border']};border-radius:2px;min-height:24px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )
        self.right_inner.setStyleSheet(
            "background:transparent;" if transparent else ""
        )

    def focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def external_search(self, text: str):
        self.search_box.setText(text)
        self.search_box.setFocus()
        self._submit()

    def _submit(self):
        text = self.search_box.text().strip()
        if text:
            self.searched.emit(text)

    def _on_typing(self, text: str):
        if not text.strip():
            self._completer_model.setStringList([])
            self.result = None
            self.online_data = None
            self.result_page.hide()
            self.empty.show()
            self.chips_row.show()
            self.title.setText("查词")
            self.status.setText("")

    def _update_completions(self, text: str):
        try:
            words = self.app.store.custom_suggest(text, 12) if text.strip() else []
        except Exception:
            words = []
        self._completer_model.setStringList(words)
        if words:
            self._completer.setCompletionPrefix(text)
            self._completer.complete()

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Wheel
            and self.settings.get("linked_scroll", False)
            and self.result_page.isVisible()
            and self.right_scroll.isVisible()
        ):
            pos = QCursor.pos()
            over_left = self.result_scroll.rect().contains(
                self.result_scroll.mapFromGlobal(pos)
            )
            over_right = self.right_scroll.rect().contains(
                self.right_scroll.mapFromGlobal(pos)
            )
            if over_left or over_right:
                delta = event.angleDelta().y()
                if delta:
                    self._linked_wheel(delta)
                    return True
        return super().eventFilter(obj, event)

    def _on_left_scroll(self, value: int):
        if (
            self._syncing_scroll
            or not self.settings.get("linked_scroll", False)
            or not self.right_scroll.isVisible()
        ):
            return
        self._syncing_scroll = True
        try:
            self._linked_offset = value
            right = self.right_scroll.verticalScrollBar()
            right.setValue(min(value, right.maximum()))
        finally:
            self._syncing_scroll = False

    def _linked_wheel(self, delta: int):
        left = self.result_scroll.verticalScrollBar()
        right = self.right_scroll.verticalScrollBar()
        step = max(left.singleStep(), right.singleStep(), 20)
        maximum = max(left.maximum(), right.maximum())
        self._linked_offset = max(
            0, min(maximum, self._linked_offset - int(delta / 120) * step * 3)
        )
        self._syncing_scroll = True
        try:
            left.setValue(min(self._linked_offset, left.maximum()))
            right.setValue(min(self._linked_offset, right.maximum()))
        finally:
            self._syncing_scroll = False

    def search(self, text: str, record: bool = True, push: bool = True):
        text = text.strip()
        if not text:
            return
        if push and self.result:
            current = (self.result.get("query") or "").strip()
            if current and current.lower() != text.lower():
                if not self._back_stack or self._back_stack[-1] != current:
                    self._back_stack.append(current)
                    self._back_stack = self._back_stack[-80:]
        self._update_back()
        try:
            self._completer.popup().hide()
        except Exception:
            pass
        self.search_box.setText(text)
        self.view_source = "all"
        self.chips_row.hide()
        self.empty.hide()
        self.result_page.show()
        self.status.setText("正在查询…")
        self.app.engine.search(text)

    def _update_back(self):
        if hasattr(self, "back_btn"):
            self.back_btn.setVisible(bool(self._back_stack))

    def go_back(self):
        if not self._back_stack:
            return
        target = self._back_stack.pop()
        self._update_back()
        self.search(target, record=False, push=False)

    def rerender(self):
        if self.result:
            self._render(keep_scroll=True)

    def _on_local(self, res: dict):
        self.result = res
        if self.view_source == "local" and not res.get("custom"):
            self.view_source = "all"
        self.online_data = None
        self.fulltext_results = []
        self.ft_token += 1
        kind = res.get("kind")
        if kind == "sentence":
            self.title.setText("翻译")
        elif kind == "zh":
            self.title.setText("中英互译")
        else:
            self.title.setText("查词")
        self.app.note_lookup(res)
        self._render()
        if (
            self.settings.get("fulltext_enabled", False)
            and kind in ("en", "zh")
            and len(res.get("query", "").strip()) >= 2
        ):
            token = self.ft_token
            QThreadPool.globalInstance().start(
                _FulltextJob(
                    token, res["query"], self.app.lexicon, self.ft_signals,
                    store=self.app.store,
                )
            )

    def _on_fulltext(self, token: int, text: str, data: list):
        if token != self.ft_token or not self.result or self.result.get("query") != text:
            return
        self.fulltext_results = data or []
        if self.fulltext_results:
            self._render(keep_scroll=True)

    def _on_online(self, data: dict):
        if not self.result:
            return
        self.online_data = data
        self._render(keep_scroll=True)

    # ------------------------------------------------------------------ render
    def _clear(self):
        clear_layout(self.header_layout)
        clear_layout(self.result_layout)
        clear_layout(self.right_layout)
        self.right_scroll.hide()

    def _render_fulltext(self):
        if not self.fulltext_results:
            return
        card = section_card("全文匹配", extra=label("搜索释义/例句", "faint"))
        for hit in self.fulltext_results[:15]:
            btn = QPushButton("%s  ·  %s" % (hit["word"], hit["source"]))
            btn.setObjectName("wordlink")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, w=hit["word"]: self.app.lookup_word(w))
            card.body().addWidget(btn, 0, Qt.AlignLeft)
            if hit.get("snippet"):
                card.body().addWidget(label(hit["snippet"], "sub", wrap=True))
        idx = self.result_layout.count() - 1
        item = self.result_layout.itemAt(idx) if idx >= 0 else None
        if item is not None and item.spacerItem() is not None:
            self.result_layout.insertWidget(idx, card)
        else:
            self.result_layout.addWidget(card)

    def _render(self, keep_scroll: bool = False):
        res = self.result
        if not res:
            return
        bar = self.result_scroll.verticalScrollBar()
        pos = bar.value()
        self._linked_offset = pos if keep_scroll else 0
        self._clear()

        if res.get("error"):
            self.result_layout.addWidget(label(res["error"], "error"))
            self.result_layout.addStretch(1)
            return

        if res["kind"] in ("en", "zh"):
            self._add_source_bar(res["kind"])

        if res["kind"] in ("en", "zh") and not self.settings.get("cn_en", True) and not self.settings.get("en_en", True):
            self._render_disabled("中英互译 / 英英互译")
            self.result_layout.addStretch(1)
            return

        if res["kind"] == "sentence":
            self._render_translation(res)
        elif res["kind"] == "zh":
            if self.settings.get("cn_en", True):
                self._render_chinese(res)
            else:
                self._render_disabled("中英互译")
        elif self._has_english(res):
            self._render_english(res)
        else:
            self._render_missing(res)

        self._render_fulltext()
        self.result_layout.addStretch(1)
        if keep_scroll:
            QTimer.singleShot(0, lambda: bar.setValue(pos))
        else:
            QTimer.singleShot(0, lambda: bar.setValue(0))
        self._update_status(res)

    def _ordered_source_keys(self):
        defaults = ["ecdict", "local", "wordnet", "collins", "youdao", "merriam"]
        raw = self.settings.get("source_order")
        order = [k for k in (raw if isinstance(raw, list) else []) if k in defaults]
        for key in defaults:
            if key not in order:
                order.append(key)
        return order

    def _ordered_right_keys(self):
        defaults = ["phrs", "web", "forms", "synonyms", "frequency"]
        raw = self.settings.get("right_order")
        order = [k for k in (raw if isinstance(raw, list) else []) if k in defaults]
        for key in defaults:
            if key not in order:
                order.append(key)
        return order

    def _add_source_bar(self, kind: str):
        labels = {
            "ecdict": "ECDICT·离线", "wordnet": "WordNet·离线",
            "local": "本地", "collins": "柯林斯·在线",
            "youdao": "有道·在线", "merriam": "韦氏·在线",
        }
        if kind == "en":
            sources = [("all", "全部")]
            for key in self._ordered_source_keys():
                if key == "local" and not (self.result or {}).get("custom"):
                    continue
                sources.append((key, labels[key]))
        else:
            sources = [("all", "全部"), ("cedict", "CC-CEDICT·离线")]
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 2)
        row.setSpacing(6)
        row.addWidget(label("解释来源", "faint"))
        for key, text in sources:
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            active = self.view_source == key
            btn.setStyleSheet(
                f"QPushButton{{border:1px solid {theme['border']};border-radius:14px;padding:3px 12px;"
                f"background:{theme['accent'] if active else theme['surface2']};"
                f"color:{theme['accentText'] if active else theme['sub']};font-size:12px;}}"
                f"QPushButton:hover{{border-color:{theme['accent']};}}"
            )
            btn.clicked.connect(lambda _=False, k=key: self._set_view_source(k))
            row.addWidget(btn)
        row.addStretch(1)
        self.header_layout.addWidget(holder)

    def _set_view_source(self, source: str):
        self.view_source = source
        self._render(keep_scroll=True)

    def _toggle_local_source(self, source: str):
        if source in self._local_open:
            self._local_open.discard(source)
        else:
            self._local_open.add(source)
        self._render(keep_scroll=True)

    @staticmethod
    def _custom_display_text(text: str) -> str:
        out = []
        for raw in (text or "").splitlines():
            s = raw.strip()
            if not s:
                continue
            s = s.replace(" | ", "; ")
            s = re.sub(r"^[>?☞\s]+", "", s)
            if "·" in s and re.match(r"^[A-Za-z]+·", s):
                s = re.sub(r"^[A-Za-z]+·[A-Za-z·0-9]*\s*", "", s)
            if s:
                out.append(s)
        return "\n".join(out)

    @classmethod
    def _custom_preview(cls, text: str, max_lines: int = 4) -> str:
        lines = cls._custom_display_text(text).splitlines()
        out = []
        for line in lines:
            # Etymology, headword respelling and dictionary codes are noise
            # in a compact result card; keep them for the expanded view.
            if re.match(r"^\[\s*(?:Date|Origin|Language):", line, re.I):
                continue
            if re.match(r"^\d*\s*W\d*\s*/", line):
                continue
            if "·" in line and "/" in line:
                continue
            if line == "=":
                continue
            out.append(line)
            if len(out) >= max_lines:
                break
        return "\n".join(out) or cls._custom_display_text(text)[:700]

    @staticmethod
    def _soft_case(text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        letters = [c for c in text if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
            text = text.lower()
            text = text[:1].upper() + text[1:]
        return text

    @classmethod
    def _category_label(cls, text: str) -> str:
        text = (text or "").strip()
        exact = {
            "ADV.": "Adverbs",
            "PHRASES": "Phrases",
            "PREP.": "Prepositions",
            "NOUN": "Nouns",
            "VERB": "Verbs",
            "ADJ.": "Adjectives",
        }
        if text.upper() in exact:
            return exact[text.upper()]
        if text.upper().startswith("VERB + "):
            return "Verb + " + text[7:].strip().lower()
        return cls._soft_case(text)

    def _render_structured(self, card, data: dict, expanded: bool, source: str = ""):
        kind = data.get("kind")
        senses = data.get("senses") or []
        limit = len(senses) if expanded else min(3, len(senses))
        for si, sense in enumerate(senses[:limit]):
            no = (sense.get("no") or "").strip()
            title = (sense.get("title") or "").strip()
            if no and not title and kind != "collocations":
                defn = (sense.get("def") or "").strip()
                card.body().addWidget(label(no + "  " + defn, "en", wrap=True))
                if expanded:
                    for ex in sense.get("examples") or []:
                        card.body().addWidget(label("• " + ex, "example", wrap=True))
                card.body().addSpacing(4)
                continue
            head = QHBoxLayout()
            head.setSpacing(8)
            if no:
                head.addWidget(label(no, "faint"))
            if title:
                head.addWidget(label(SearchPage._soft_case(title), "body"))
            gram = (sense.get("gram") or "").strip()
            if gram:
                head.addWidget(label(gram, "faint"))
            head.addStretch(1)
            card.body().addLayout(head)

            if kind == "collocations":
                groups = sense.get("groups") or []
                glimit = len(groups) if expanded else min(2, len(groups))
                for gi, group in enumerate(groups[:glimit]):
                    if group.get("label"):
                        card.body().addWidget(
                            label(SearchPage._category_label(group["label"]), "faint")
                        )
                    items = group.get("items") or []
                    ilimit = len(items) if expanded else min(12, len(items))
                    texts = [item.get("text", "") for item in items[:ilimit] if item.get("text")]
                    if texts:
                        card.body().addWidget(label(" · ".join(texts), "body", wrap=True))
                    if expanded:
                        examples = [
                            "%s — %s" % (item.get("text", ""), item["example"])
                            for item in items
                            if item.get("example")
                        ]
                        if examples:
                            if len(examples) <= 3:
                                # A handful of examples reads better inline;
                                # only hide when the list is long.
                                for ex in examples:
                                    card.body().addWidget(
                                        label("• " + ex, "example", wrap=True)
                                    )
                            else:
                                key = "%s|%s|%s|%s" % (source, si, gi, no)
                                opened = key in self._example_open
                                btn = QPushButton(
                                    "收起例句" if opened else "例句 %d 条" % len(examples)
                                )
                                btn.setObjectName("chip")
                                btn.setCursor(Qt.PointingHandCursor)
                                btn.clicked.connect(
                                    lambda _=False, k=key: self._toggle_examples(k)
                                )
                                card.body().addWidget(btn, 0, Qt.AlignLeft)
                                if opened:
                                    for ex in examples:
                                        card.body().addWidget(
                                            label("• " + ex, "example", wrap=True)
                                        )
            else:
                defn = (sense.get("def") or "").strip()
                if defn:
                    card.body().addWidget(label(defn, "en", wrap=True))
                if expanded:
                    for ex in sense.get("examples") or []:
                        card.body().addWidget(label("• " + ex, "example", wrap=True))
            card.body().addSpacing(4)

        if expanded and data.get("etym"):
            card.body().addSpacing(2)
            card.body().addWidget(hline())
            card.body().addWidget(label("词源", "faint"))
            card.body().addWidget(label(data["etym"], "sub", wrap=True))

    def _toggle_examples(self, key: str):
        if key in self._example_open:
            self._example_open.discard(key)
        else:
            self._example_open.add(key)
        self._render(keep_scroll=True)

    def _update_status(self, res):
        parts = []
        if res.get("entry"):
            parts.append("ECDICT 离线词典")
        if res.get("wordnet"):
            parts.append("WordNet 英英词典")
        if res.get("cedict"):
            parts.append("CC-CEDICT 离线词典")
        if self.online_data and self.online_data.get("youdao"):
            parts.append("有道在线补充")
        if self.online_data and self.online_data.get("merriam"):
            parts.append("Merriam-Webster 在线")
        if self.online_data and self.online_data.get("dictionary"):
            parts.append("Free Dictionary 在线")
        if not parts:
            self.status.setText("")
        else:
            self.status.setText("来源：" + " · ".join(parts))

    def _missing_text(self, res):
        return "没有找到「%s」的释义" % res["query"]

    # ------------------------------------------------------------------ english
    def _render_english(self, res):
        entry = res.get("entry") or {}
        word = entry.get("word") or res["query"]
        online = self.online_data or {}
        od = online.get("dictionary") or {}
        yd = online.get("youdao") or {}
        mw = online.get("merriam") or {}

        # header
        head = Card()
        top = QHBoxLayout()
        top.setSpacing(12)
        wl = label(word, "word")
        top.addWidget(wl, 0, Qt.AlignBottom)
        phonetic = (
            entry.get("phonetic")
            or yd.get("phonetic_us")
            or yd.get("phonetic_uk")
            or self._online_phonetic(od)
            or ""
        )
        ph_text = f"/{phonetic}/" if phonetic and not phonetic.startswith("/") else phonetic
        ph = label(ph_text, "phonetic")
        if phonetic:
            top.addWidget(ph, 0, Qt.AlignBottom)
        top.addStretch(1)

        uk = QPushButton("英式")
        uk.setObjectName("chip")
        uk.setIcon(icons.svg_icon("volume", theme["sub"], 13))
        uk.setIconSize(QSize(13, 13))
        uk.setToolTip("英式发音")
        uk.setCursor(Qt.PointingHandCursor)
        uk.clicked.connect(lambda: self.app.speak(word, "uk"))
        us = QPushButton("美式")
        us.setObjectName("chip")
        us.setIcon(icons.svg_icon("volume", theme["sub"], 13))
        us.setIconSize(QSize(13, 13))
        us.setToolTip("美式发音")
        us.setCursor(Qt.PointingHandCursor)
        us.clicked.connect(lambda: self.app.speak(word, "us"))
        top.addWidget(uk)
        top.addWidget(us)

        self.add_btn = QPushButton()
        self.add_btn.setObjectName("primary")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self._sync_add_button(word, entry)
        self.add_btn.clicked.connect(lambda: self._toggle_word(word, entry))
        top.addSpacing(6)
        top.addWidget(self.add_btn)
        head.body().addLayout(top)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        tags = entry.get("tags") or []
        for i, tag in enumerate(tags[:self._cap(5)]):
            fg, bg = TAG_COLORS[i % len(TAG_COLORS)]
            meta_row.addWidget(Chip(tag, fg, bg))
        if entry.get("oxford"):
            meta_row.addWidget(Chip("牛津核心", "green", "greenSoft"))
        if entry.get("collins"):
            meta_row.addWidget(RangeBadge(entry["collins"]))
            meta_row.addWidget(label("柯林斯 %d 星" % entry["collins"], "faint"))
        if entry.get("bnc"):
            meta_row.addWidget(label("BNC #%d" % entry["bnc"], "faint"))
        target_exam = self.settings.get("target_exam", "")
        if target_exam:
            exam_name = EXAM_NAMES.get(target_exam, target_exam)
            in_list = exam_name in (entry.get("tags") or [])
            meta_row.addWidget(Chip(
                f"{exam_name} 词表" if in_list else f"不在{exam_name}词表",
                "green" if in_list else "amber",
                "greenSoft" if in_list else "amberSoft",
            ))
        meta_row.addStretch(1)
        head.body().addLayout(meta_row)
        self.header_layout.addWidget(head)

        base = res.get("meta", {}).get("base")
        if base:
            self.header_layout.addWidget(
                label("「%s」是「%s」的变化形式，已按原形显示。" % (res["query"], base), "faint")
            )
        lookup_variant = (online or {}).get("lookup_variant")
        if lookup_variant:
            self.header_layout.addWidget(
                label("在线词典没有「%s」的词条，已按「%s」查询。" % (res["query"], lookup_variant), "faint")
            )

        custom = res.get("custom") or []
        if custom and self.view_source in ("all", "ecdict", "local"):
            names = []
            for item in custom:
                name = (item.get("source") or "本地词库").strip()
                if name not in names:
                    names.append(name)
            self.header_layout.addWidget(
                label("已加载本地词典：%s" % " / ".join(names), "faint", wrap=True)
            )

        linked = bool(self.settings.get("linked_scroll", False))
        self.right_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if linked else Qt.ScrollBarAsNeeded
        )
        fixed_right = bool(self.settings.get("right_fixed", False)) or linked
        if fixed_right:
            left = self.result_layout
            right = self.right_layout
        else:
            left = QVBoxLayout()
            right = QVBoxLayout()
        left.setSpacing(14)
        right.setSpacing(14)
        cards = {}
        right_cards = {}

        def put_right(key, card):
            card.setMaximumWidth(290)
            card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            right_cards.setdefault(key, []).append(card)

        def put(key, card):
            cards.setdefault(key, []).append(card)

        # User-provided local dictionary entries (never uploaded)
        if custom and self.view_source in ("all", "ecdict", "local"):
            card = section_card("本地词典", extra=label("每本可单独展开", "faint"))
            last_source = None
            first_entry = True
            for item in custom[:8]:
                source = (item.get("source") or "本地词库").strip()
                is_open = source in self._local_open
                if source != last_source:
                    if not first_entry:
                        card.body().addSpacing(10)
                        card.body().addWidget(hline())
                        card.body().addSpacing(4)
                    source_row = QHBoxLayout()
                    source_row.setSpacing(8)
                    source_row.addWidget(label(source, "faint", wrap=True), 1)
                    expand_btn = QPushButton("收起" if is_open else "展开")
                    expand_btn.setObjectName("chip")
                    expand_btn.setCursor(Qt.PointingHandCursor)
                    expand_btn.clicked.connect(
                        lambda _=False, s=source: self._toggle_local_source(s)
                    )
                    source_row.addWidget(expand_btn)
                    card.body().addLayout(source_row)
                    last_source = source
                    first_entry = False
                else:
                    card.body().addSpacing(6)
                    card.body().addWidget(hline())
                    card.body().addSpacing(2)
                top = QHBoxLayout()
                top.setSpacing(8)
                top.addWidget(label(item.get("word", ""), "body"))
                if item.get("phonetic"):
                    top.addWidget(label("/%s/" % item["phonetic"].strip("/"), "phonetic"))
                structured = custom_fmt.decode(item.get("definition", ""))
                if structured and structured.get("pos"):
                    top.addWidget(label(structured["pos"], "faint"))
                top.addStretch(1)
                card.body().addLayout(top)
                if structured:
                    self._render_structured(card, structured, is_open, source)
                    card.body().addSpacing(6)
                    continue
                if item.get("translation"):
                    txt = (
                        self._custom_display_text(item["translation"])
                        if is_open
                        else self._custom_preview(item["translation"], 3)
                    )
                    card.body().addWidget(label(txt, "def", wrap=True))
                if item.get("definition"):
                    txt = (
                        self._custom_display_text(item["definition"])
                        if is_open
                        else self._custom_preview(item["definition"], 5)
                    )
                    card.body().addWidget(label(txt, "en", wrap=True))
                card.body().addSpacing(6)
            put("local", card)

        # Chinese definitions: online first when available, offline fallback
        online_cn = (
            bool(yd.get("cn"))
            and self.settings.get("online_first", True)
            and self.view_source in ("all", "youdao")
        )
        fallback_source = (
            (self.view_source == "collins" and not yd.get("collins"))
            or (self.view_source == "merriam" and not mw.get("entries"))
            or (self.view_source == "youdao" and not yd.get("cn"))
        )
        parallel = bool(self.settings.get("parallel_sources", False) and self.view_source == "all")
        show_offline_cn = (
            bool(entry.get("translation"))
            and (self.view_source in ("all", "ecdict") or fallback_source)
            and (parallel or not online_cn)
        )
        if self.settings.get("cn_en", True):
            if show_offline_cn:
                if fallback_source:
                    left.addWidget(
                        label("当前在线来源没有返回结果，以下为离线 ECDICT 释义。", "faint")
                    )
                card = section_card(
                    "中文释义",
                    extra=label(
                        "离线 · ECDICT · 在线无结果" if fallback_source else "离线 · ECDICT",
                        "faint",
                    ) if (parallel or fallback_source) else None,
                )
                pos_data = entry.get("pos") or {}
                for code, name, text in pos_data.get("groups", []):
                    row = QHBoxLayout()
                    row.setSpacing(10)
                    row.addWidget(Chip(name, "accent", "accentSoft"), 0, Qt.AlignTop)
                    body = label(self._format_senses(text), "def", wrap=True)
                    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    row.addWidget(body, 1)
                    card.body().addLayout(row)
                if pos_data.get("network"):
                    card.body().addWidget(hline())
                    net = QHBoxLayout()
                    net.setSpacing(6)
                    net.addWidget(label("网络", "faint"), 0, Qt.AlignTop)
                    net.addWidget(label("；".join(pos_data["network"])[:220], "sub", wrap=True), 1)
                    card.body().addLayout(net)
                if not pos_data.get("groups") and not pos_data.get("network"):
                    card.body().addWidget(label(entry.get("translation", ""), "def", wrap=True))
                put("ecdict", card)
            if online_cn and self.view_source in ("all", "youdao") and (parallel or not show_offline_cn):
                card = section_card("中文释义", extra=label("在线 · 有道", "faint"))
                for line in yd["cn"][:self._cap(4)]:
                    import re as _re

                    m = _re.match(r"^([a-zA-Z]{1,6}\.)\s*(.+)$", line)
                    if m:
                        row = QHBoxLayout()
                        row.setSpacing(10)
                        row.addWidget(Chip(self._pos_cn(m.group(1).rstrip(".")), "accent", "accentSoft"), 0, Qt.AlignTop)
                        row.addWidget(label(self._format_senses(m.group(2)), "def", wrap=True), 1)
                        card.body().addLayout(row)
                    else:
                        card.body().addWidget(label(line, "def", wrap=True))
                put(
                    "ecdict"
                    if self.view_source == "all" and not show_offline_cn
                    else "youdao",
                    card,
                )

        # English definitions: online first, offline WordNet fallback
        prefer_online = (
            self.view_source in ("all", "youdao")
            and self.settings.get("online_first", True)
            and not parallel
            and bool(yd.get("en") or yd.get("collins"))
        )
        use_online_en = prefer_online and bool(yd.get("en")) and not (
            self.view_source == "all" and yd.get("collins")
        )
        if self.settings.get("en_en", True) and self.view_source in ("all", "wordnet", "youdao"):
            wn = [] if prefer_online else (res.get("wordnet") or [])
            if not wn and yd.get("en") and not (self.view_source == "all" and yd.get("collins")):
                wn = [
                    {"pos": self._pos_cn(item.get("pos", "")), "definition": d, "examples": [], "synonyms": []}
                    for item in yd["en"]
                    for d in item.get("defs", [])[:4]
                ]
            if not wn and od.get("meanings"):
                wn = [
                    {
                        "pos": self._pos_cn(m.get("pos", "")),
                        "definition": d.get("definition", ""),
                        "examples": [d.get("example")] if d.get("example") else [],
                        "synonyms": d.get("synonyms", []),
                    }
                    for m in od.get("meanings", [])
                    for d in m.get("definitions", [])
                ]
            if wn:
                card = section_card(
                    "英英释义",
                    extra=label("在线 · 有道" if use_online_en else "离线 · WordNet", "faint"),
                )
                grouped = {}
                for item in wn:
                    grouped.setdefault(item["pos"], []).append(item)
                for pos, items in grouped.items():
                    chip = Chip(pos, "purple", "purpleSoft")
                    card.body().addWidget(chip, 0, Qt.AlignLeft)
                    for item in items[:self._cap(4)]:
                        d = label(item["definition"], "en", wrap=True)
                        card.body().addWidget(d)
                        for ex in item.get("examples", [])[:self._cap(2)]:
                            ex_lb = label("“%s”" % ex, "example", wrap=True)
                            card.body().addWidget(ex_lb)
                    card.body().addSpacing(4)
                put("wordnet", card)
            if od.get("meanings") and res.get("wordnet"):
                put("youdao", self._online_dict_card(od))

        # Merriam-Webster official API
        if mw.get("entries") and self.view_source in ("all", "merriam"):
            variant = "Learner's" if mw.get("variant") == "learners" else "Collegiate"
            card = section_card("韦氏词典", extra=label("Merriam-Webster · " + variant, "faint"))
            for item in mw["entries"][:self._cap(5)]:
                if item.get("pos"):
                    card.body().addWidget(Chip(item["pos"], "green", "greenSoft"), 0, Qt.AlignLeft)
                for definition in item.get("defs", [])[:self._cap(4)]:
                    card.body().addWidget(label(definition, "en", wrap=True))
                card.body().addSpacing(2)
            put("merriam", card)

        # Collins authoritative definitions
        if yd.get("collins") and self.view_source in ("all", "collins"):
            card = section_card("柯林斯释义", extra=label("在线 · 柯林斯", "faint"))
            for item in yd["collins"][:self._cap(4)]:
                row = QHBoxLayout()
                row.setSpacing(10)
                if item.get("pos"):
                    row.addWidget(Chip(item["pos"], "purple", "purpleSoft"), 0, Qt.AlignTop)
                row.addWidget(label(item["def"], "en", wrap=True), 1)
                card.body().addLayout(row)
                for ex in item.get("examples", [])[:self._cap(2)]:
                    card.body().addWidget(label("“%s”" % ex["en"], "example", wrap=True))
                    if ex.get("zh"):
                        card.body().addWidget(label(ex["zh"], "sub", wrap=True))
                card.body().addSpacing(2)
            put("collins", card)

        # bilingual examples from Youdao
        if yd.get("examples") and self.view_source in ("all", "youdao"):
            card = section_card("例句", extra=label("在线 · 有道", "faint"))
            for ex in yd["examples"][:self._cap(5)]:
                card.body().addWidget(label(ex["en"], "en", wrap=True))
                if ex.get("zh"):
                    card.body().addWidget(label(ex["zh"], "sub", wrap=True))
                card.body().addSpacing(2)
            put("youdao", card)

        # collocations / phrases
        if yd.get("phrs") and self.view_source in ("all", "youdao"):
            card = section_card("搭配", extra=label("在线 · 有道", "faint"))
            for phr in yd["phrs"][:self._cap(10)]:
                card.body().addWidget(label(phr["en"], "en", wrap=True))
                if phr.get("zh"):
                    card.body().addWidget(label(phr["zh"], "sub", wrap=True))
                card.body().addSpacing(2)
            put_right("phrs", card)

        # exam-style usage examples from Collins
        if self.settings.get("target_exam") and yd.get("exam_sents") and self.view_source in ("all", "youdao"):
            exam_name = EXAM_NAMES.get(self.settings.get("target_exam"), "")
            card = section_card("考法例句", extra=label(f"柯林斯 · {exam_name}", "faint"))
            for sent in yd["exam_sents"][:self._cap(4)]:
                card.body().addWidget(label(sent["en"], "en", wrap=True))
                if sent.get("zh"):
                    card.body().addWidget(label(sent["zh"], "sub", wrap=True))
                card.body().addSpacing(2)
            put("youdao", card)

        # Place top-level source cards in the user's order.
        order = self._ordered_source_keys()
        for key in order:
            for card in cards.get(key, []):
                left.addWidget(card)
        for key, items in cards.items():
            if key not in order:
                for card in items:
                    left.addWidget(card)

        if not cards and right.count() == 0:
            card = section_card("释义")
            card.body().addWidget(
                label("离线词典里没有找到「%s」。" % res["query"], "sub", wrap=True)
            )
            if res.get("suggestions"):
                row = FlowLayout(hspacing=8, vspacing=8)
                row.addWidget(label("你是不是想查：", "faint"))
                for s in res["suggestions"]:
                    row.addWidget(clickable_chip(s, self.external_search))
                holder = QWidget()
                holder.setLayout(row)
                card.body().addWidget(holder)
            left.addWidget(card)

        # right column: web senses, forms, synonyms, frequency
        if yd.get("web") and self.view_source in ("all", "youdao"):
            card = section_card("网络释义", extra=label("仅供参考", "faint"))
            flow = FlowLayout(hspacing=6, vspacing=6)
            for sense in yd["web"][:self._cap(8)]:
                flow.addWidget(clickable_chip(sense, self.external_search))
            holder = QWidget()
            holder.setLayout(flow)
            card.body().addWidget(holder)
            put_right("web", card)

        forms = entry.get("exchange") or []
        if forms:
            card = section_card("词形变化")
            grid = QVBoxLayout()
            grid.setSpacing(6)
            for name, val in forms[:self._cap(8)]:
                row = QHBoxLayout()
                row.addWidget(label(name, "faint"))
                row.addStretch(1)
                b = QPushButton(val)
                b.setObjectName("chip")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, v=val: self.external_search(v))
                row.addWidget(b)
                grid.addLayout(row)
            card.body().addLayout(grid)
            put_right("forms", card)

        syns = self._synonyms(entry, res, online)
        if syns:
            card = section_card("同义词")
            flow = FlowLayout(hspacing=6, vspacing=6)
            for s in syns[:self._cap(14)]:
                flow.addWidget(clickable_chip(s, self.external_search))
            holder = QWidget()
            holder.setLayout(flow)
            card.body().addWidget(holder)
            put_right("synonyms", card)

        if entry.get("frq") or entry.get("bnc"):
            card = section_card("词频")
            for name, val in (("当代语料", entry.get("frq")), ("BNC 排名", entry.get("bnc"))):
                if val:
                    row = QHBoxLayout()
                    row.addWidget(label(name, "faint"))
                    row.addStretch(1)
                    row.addWidget(label("#%d" % val, "sub"))
                    card.body().addLayout(row)
            put_right("frequency", card)

        for key in self._ordered_right_keys():
            for card in right_cards.get(key, []):
                right.addWidget(card)
        for key, items in right_cards.items():
            if key not in self._ordered_right_keys():
                for card in items:
                    right.addWidget(card)

        has_right = bool(right_cards)
        left.addStretch(1)
        if fixed_right:
            if has_right:
                right.addStretch(1)
            self.right_scroll.setVisible(has_right)
        else:
            self.right_scroll.hide()
            if has_right:
                holder = QWidget()
                holder.setLayout(right)
                holder.setFixedWidth(300)
                holder.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
                columns = QHBoxLayout()
                columns.setSpacing(14)
                columns.addLayout(left, 1)
                columns.addWidget(holder, 0, Qt.AlignTop)
                self.result_layout.addLayout(columns)
            else:
                self.result_layout.addLayout(left)

        if linked:
            QTimer.singleShot(0, self._apply_linked_offset)

    def _apply_linked_offset(self):
        left = self.result_scroll.verticalScrollBar()
        right = self.right_scroll.verticalScrollBar()
        self._linked_offset = max(
            0, min(self._linked_offset, max(left.maximum(), right.maximum()))
        )
        self._syncing_scroll = True
        try:
            left.setValue(min(self._linked_offset, left.maximum()))
            right.setValue(min(self._linked_offset, right.maximum()))
        finally:
            self._syncing_scroll = False

    # ------------------------------------------------------------------ chinese
    def _render_chinese(self, res):
        entries = res.get("cedict") or []
        reverse = res.get("reverse") or []
        word = entries[0]["simp"] if entries else res["query"]
        head = Card()
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(label(word, "word"), 0, Qt.AlignBottom)
        if entries:
            top.addWidget(label(entries[0].get("pinyin") or "", "phonetic"), 0, Qt.AlignBottom)
            spk = IconButton("volume", None, 16, "朗读", box=30)
            spk.clicked.connect(lambda: self.app.speak(word, "us"))
            top.addWidget(spk)
        top.addStretch(1)
        add = QPushButton("+ 生词本")
        add.setObjectName("primary")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(lambda: self._toggle_word(word, {"word": word, "translation": ""}))
        top.addWidget(add)
        head.body().addLayout(top)
        if entries and entries[0]["trad"] != entries[0]["simp"]:
            head.body().addWidget(label("繁体：" + entries[0]["trad"], "faint"))
        self.header_layout.addWidget(head)

        if entries:
            card = section_card("英文释义")
            for e in entries[:self._cap(4)]:
                row = QVBoxLayout()
                row.setSpacing(4)
                top_row = QHBoxLayout()
                top_row.addWidget(label(e["simp"], "def"))
                top_row.addWidget(label(e["pinyin"], "phonetic"))
                top_row.addStretch(1)
                row.addLayout(top_row)
                for g in e["glosses"][:self._cap(5)]:
                    row.addWidget(label("· " + g, "en", wrap=True))
                card.body().addLayout(row)
                card.body().addWidget(hline())
            self.result_layout.addWidget(card)
        else:
            card = section_card("英文释义")
            card.body().addWidget(
                label("CC-CEDICT 没有收录「%s」，可以看看下面的候选词或整句翻译。" % res["query"], "sub", wrap=True)
            )
            if reverse:
                for r in reverse[:self._cap(5)]:
                    row = QHBoxLayout()
                    b = QPushButton(r["word"])
                    b.setObjectName("chip")
                    b.clicked.connect(lambda _=False, w=r["word"]: self.external_search(w))
                    row.addWidget(b)
                    row.addWidget(label((r.get("translation") or "").replace("\n", "；")[:90], "faint", wrap=True), 1)
                    card.body().addLayout(row)
            self.result_layout.addWidget(card)

        if res.get("suggestions"):
            card = section_card("相关词")
            flow = FlowLayout(hspacing=6, vspacing=6)
            for s in res["suggestions"][:self._cap(12)]:
                flow.addWidget(clickable_chip(s, self.external_search))
            holder = QWidget()
            holder.setLayout(flow)
            card.body().addWidget(holder)
            self.result_layout.addWidget(card)

        online = self.online_data or {}
        if online.get("translation"):
            self._translation_card(online["translation"])

    # ------------------------------------------------------------------ translation
    def _render_translation(self, res):
        if not self.settings.get("cn_en", True):
            card = section_card("翻译")
            card.body().addWidget(
                label("「中英互译」当前是关闭的。到设置里打开后即可翻译整句。", "sub", wrap=True)
            )
            self.result_layout.addWidget(card)
            return
        online = self.online_data or {}
        trans = online.get("translation")
        if trans:
            self._translation_card(trans)
            return
        holder = Card()
        holder.body().addWidget(label("正在翻译…", "sub"))
        holder.body().addWidget(label(res["query"], "en", wrap=True))
        self.result_layout.addWidget(holder)

    def _translation_card(self, trans: dict):
        pair = QWidget()
        pr = QHBoxLayout(pair)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(8)
        label_text = "中文 → 英文" if trans.get("src") == "zh" else "英文 → 中文"
        pr.addWidget(Chip(label_text, "accent", "accentSoft"))
        pr.addWidget(label(self.app.provider_label(), "faint"))
        card = section_card("翻译", extra=pair)
        src = label(trans.get("source", ""), "en", wrap=True)
        src.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.body().addWidget(src)
        arrow = QLabel("↓")
        arrow.setStyleSheet(f"color:{theme['accent']};font-size:15px;font-weight:700;")
        card.body().addWidget(arrow)
        if trans.get("error"):
            card.body().addWidget(label(trans["error"], "error", wrap=True))
        else:
            out = label(trans.get("text", ""), "def", wrap=True)
            out.setTextInteractionFlags(Qt.TextSelectableByMouse)
            card.body().addWidget(out)
            row = QHBoxLayout()
            row.addStretch(1)
            copy = QPushButton("复制译文")
            copy.setObjectName("chip")
            copy.clicked.connect(lambda: self._copy(trans.get("text", ""), copy))
            row.addWidget(copy)
            card.body().addLayout(row)
        self.result_layout.addWidget(card)

    def _copy(self, text: str, btn: QPushButton):
        QGuiApplication.clipboard().setText(text)
        old = btn.text()
        btn.setText("已复制")
        QTimer.singleShot(1200, lambda: btn.setText(old))

    def _has_english(self, res) -> bool:
        cn_en = self.settings.get("cn_en", True)
        en_en = self.settings.get("en_en", True)
        entry = res.get("entry")
        if res.get("custom"):
            return True
        if entry and cn_en and entry.get("translation"):
            return True
        if entry and en_en and entry.get("definition"):
            return True
        if en_en and res.get("wordnet"):
            return True
        if en_en and self.online_data and self.online_data.get("dictionary"):
            return True
        if en_en and self.online_data and self.online_data.get("youdao"):
            return True
        if en_en and self.online_data and self.online_data.get("merriam"):
            return True
        return False

    def _render_disabled(self, feature: str):
        card = section_card("功能已关闭")
        card.body().addWidget(
            label("「%s」当前是关闭的，所以这里没有显示结果。" % feature, "sub", wrap=True)
        )
        card.body().addWidget(label("到「设置 → 词典与翻译」里打开即可。", "faint"))
        self.result_layout.addWidget(card)

    def _online_dict_card(self, od: dict):
        card = section_card("在线词典", extra=label("Free Dictionary", "faint"))
        for m in od.get("meanings", [])[:3]:
            pos = self._pos_cn(m.get("pos", ""))
            card.body().addWidget(Chip(pos, "green", "greenSoft"), 0, Qt.AlignLeft)
            for d in m.get("definitions", [])[:3]:
                card.body().addWidget(label(d.get("definition", ""), "en", wrap=True))
                if d.get("example"):
                    card.body().addWidget(label("“%s”" % d["example"], "example", wrap=True))
            card.body().addSpacing(3)
        return card

    def _render_missing(self, res):
        card = section_card("没有找到")
        card.body().addWidget(
            label("离线词典里没有「%s」。可以检查拼写，或者试试别的词。" % res["query"], "sub", wrap=True)
        )
        if res.get("suggestions"):
            flow = FlowLayout(hspacing=6, vspacing=6)
            for s in res["suggestions"]:
                flow.addWidget(clickable_chip(s, self.app.lookup_word))
            holder = QWidget()
            holder.setLayout(flow)
            card.body().addWidget(holder)
        self.result_layout.addWidget(card)

    # ------------------------------------------------------------------ helpers
    def _cap(self, n: int) -> int:
        return 10000 if self.settings.get("full_content") else n

    @staticmethod
    def _format_senses(text: str) -> str:
        parts = [p.strip() for p in text.replace(";", "；").split("；") if p.strip()]
        if len(parts) <= 1:
            return text
        return "\n".join("· " + p for p in parts)

    @staticmethod
    def _pos_cn(pos: str) -> str:
        pos = (pos or "").strip().rstrip(".")
        return {
            "noun": "名词", "verb": "动词", "adjective": "形容词", "adverb": "副词",
            "pronoun": "代词", "preposition": "介词", "conjunction": "连词",
            "interjection": "感叹词", "determiner": "限定词", "numeral": "数词",
            "n": "名词", "v": "动词", "adj": "形容词", "adv": "副词", "prep": "介词",
            "pron": "代词", "conj": "连词", "num": "数词", "art": "冠词", "int": "感叹词",
        }.get(pos, pos or "释义")

    def _online_phonetic(self, od: dict) -> str:
        for ph in od.get("phonetics", []):
            if ph.get("text"):
                return ph["text"]
        return ""

    def _synonyms(self, entry, res, online):
        out = []
        for item in res.get("wordnet") or []:
            for s in item.get("synonyms", []):
                if s not in out and s != res["query"].lower():
                    out.append(s)
        for s in online.get("synonyms") or []:
            if s not in out:
                out.append(s)
        return out

    def _sync_add_button(self, word: str, entry):
        exists = self.app.store.has_word(word)
        self.add_btn.setMinimumWidth(100)
        if exists:
            self.add_btn.setText("✓ 已加入")
            self.add_btn.setObjectName("chip")
            self.add_btn.setStyleSheet(
                f"QPushButton{{background:transparent;border:1px solid {theme['border']};"
                f"color:{theme['green']};padding:8px 14px;border-radius:10px;font-weight:600;}}"
                f"QPushButton:hover{{border-color:{theme['green']};}}"
            )
        else:
            self.add_btn.setText("+ 生词本")
            self.add_btn.setObjectName("primary")
            self.add_btn.setStyleSheet("")

    def _toggle_word(self, word: str, entry):
        if self.app.store.has_word(word):
            self.app.store.remove_word(word)
        else:
            phonetic = entry.get("phonetic", "") if entry else ""
            brief = ""
            if entry and entry.get("translation"):
                lines = [l for l in entry["translation"].split("\n") if l.strip()]
                brief = lines[0][:90] if lines else ""
            self.app.store.add_word(word, phonetic, brief)
        if hasattr(self, "add_btn"):
            self._sync_add_button(word, entry)
        self.app.update_ball_badge()
        self.app.wordbook_changed.emit()


# =========================================================================== wordbook
class WordbookPage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 24, 30, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(PageHeader("生词本", "收藏的单词都在这里，点击即可重新查询"))
        head.addStretch(1)
        self.count_lb = label("", "faint")
        head.addWidget(self.count_lb)
        self.review_btn = QPushButton("开始复习")
        self.review_btn.setObjectName("chip")
        self.review_btn.clicked.connect(self.start_review)
        head.addWidget(self.review_btn)
        self.list_btn = QPushButton("返回列表")
        self.list_btn.setObjectName("chip")
        self.list_btn.clicked.connect(self.end_review)
        self.list_btn.hide()
        head.addWidget(self.list_btn)
        exp = QPushButton("导出 CSV")
        exp.setObjectName("chip")
        exp.clicked.connect(self.export)
        head.addWidget(exp)
        lay.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索生词…")
        self.search.setFixedHeight(38)
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.list_lay = QVBoxLayout(self.inner)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(8)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)
        self.review_mode = False
        self.review_queue = []
        self.review_index = 0
        self.review_revealed = False
        self.refresh()

    # ------------------------------------------------------------------ review
    def start_review(self):
        self.review_queue = self.app.store.due_words(60)
        if not self.review_queue:
            self._show_review_empty()
            return
        self.review_mode = True
        self.review_index = 0
        self.review_revealed = False
        self.search.hide()
        self.review_btn.hide()
        self.list_btn.show()
        self.count_lb.setText("待复习 %d 个" % len(self.review_queue))
        self._show_review()

    def end_review(self):
        self.review_mode = False
        self.search.show()
        self.list_btn.hide()
        self.review_btn.show()
        self.refresh()

    def _show_review_empty(self):
        clear_layout(self.list_lay)
        card = Card()
        card.body().addWidget(label("今天没有到期的生词", "h2"))
        card.body().addWidget(label("新加入的单词会立即进入复习队列。", "sub"))
        self.list_lay.addWidget(card)
        self.list_lay.addStretch(1)

    def _show_review(self):
        clear_layout(self.list_lay)
        if self.review_index >= len(self.review_queue):
            card = Card()
            card.body().addWidget(label("这一轮复习完成", "h2"))
            card.body().addWidget(label("剩下的到期单词会排到下一轮。", "sub"))
            back = QPushButton("返回生词本")
            back.setObjectName("primary")
            back.clicked.connect(self.end_review)
            card.body().addWidget(back, 0, Qt.AlignLeft)
            self.list_lay.addWidget(card)
            self.list_lay.addStretch(1)
            return
        w = self.review_queue[self.review_index]
        card = Card()
        card.body().addWidget(label("%d / %d" % (self.review_index + 1, len(self.review_queue)), "faint"))
        word = label(w["word"], "word")
        f = word.font()
        f.setPixelSize(34)
        word.setFont(f)
        card.body().addWidget(word)
        if w.get("phonetic"):
            card.body().addWidget(label("/%s/" % w["phonetic"].strip("/"), "phonetic"))
        if not self.review_revealed:
            reveal = QPushButton("显示释义")
            reveal.setObjectName("primary")
            reveal.setMinimumHeight(42)
            reveal.clicked.connect(self._reveal_review)
            card.body().addWidget(reveal, 0, Qt.AlignLeft)
            card.body().addWidget(label("先自己回忆一遍，再显示释义并评分。", "faint"))
            self.list_lay.addWidget(card)
            self.list_lay.addStretch(1)
            return
        if w.get("brief"):
            card.body().addWidget(label(w["brief"], "def", wrap=True))
        preview = self.app.store.preview_word(w["word"])
        hint = QHBoxLayout()
        for text, rating, obj in (
            ("忘记", 1, "chip"), ("模糊", 2, "chip"), ("记得", 3, "primary"), ("简单", 4, "chip")
        ):
            btn = QPushButton(self._review_label(text, preview.get(rating)))
            btn.setObjectName(obj)
            btn.setMinimumHeight(42)
            btn.clicked.connect(lambda _=False, r=rating: self._grade(r))
            hint.addWidget(btn)
        card.body().addLayout(hint)
        card.body().addWidget(label("只有本轮第一次作答计入记忆；答错会按 FSRS 排到稍后复习。", "faint"))
        self.list_lay.addWidget(card)
        self.list_lay.addStretch(1)

    def _reveal_review(self):
        self.review_revealed = True
        self._show_review()

    @staticmethod
    def _review_label(text: str, seconds) -> str:
        if seconds is None:
            return text
        m = int(seconds // 60)
        if m < 1:
            span = "<1分"
        elif m < 60:
            span = "%d分" % m
        else:
            h = m // 60
            if h < 24:
                span = "%d小时" % h
            else:
                d = h // 24
                span = "%d天" % d if d < 31 else "%d个月" % max(1, d // 30)
        return "%s · %s" % (text, span)

    def _grade(self, rating: int):
        if self.review_index >= len(self.review_queue):
            return
        word = self.review_queue[self.review_index]["word"]
        self.app.store.review_word(word, rating)
        self.app.update_ball_badge()
        self.review_revealed = False
        self.review_index += 1
        self._show_review()

    def refresh(self):
        clear_layout(self.list_lay)
        words = self.app.store.words(self.search.text().strip())
        self.count_lb.setText("%d 个单词" % len(words))
        due = self.app.store.due_count()
        self.review_btn.setText("开始复习（%d）" % due if due else "开始复习")
        if not words:
            self.list_lay.addWidget(EmptyState("生词本还是空的", "查词时点一下「+ 生词本」，单词就会收在这里。", "star"))
            self.list_lay.addStretch(1)
            return
        for w in words:
            self.list_lay.addWidget(self._row(w))
        self.list_lay.addStretch(1)

    def _row(self, w: dict) -> QWidget:
        card = Card()
        card.body().setContentsMargins(18, 12, 14, 12)
        row = QHBoxLayout()
        row.setSpacing(12)
        info = QVBoxLayout()
        info.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        word = QPushButton(w["word"])
        word.setObjectName("wordlink")
        word.setCursor(Qt.PointingHandCursor)
        f = word.font()
        f.setFamily("Georgia")
        f.setPixelSize(18)
        f.setWeight(QFont.DemiBold)
        word.setFont(f)
        word.clicked.connect(lambda _=False, x=w["word"]: self.app.lookup_word(x))
        top.addWidget(word)
        if w.get("phonetic"):
            top.addWidget(label(w["phonetic"], "phonetic"))
        top.addStretch(1)
        info.addLayout(top)
        if w.get("brief"):
            info.addWidget(label(w["brief"], "sub", wrap=True))
        row.addLayout(info, 1)
        row.addWidget(label(time.strftime("%m-%d", time.localtime(w["ts"])), "faint"))
        del_btn = IconButton("trash", card, 15, "移除", box=30)
        del_btn.clicked.connect(lambda _=False, x=w["word"]: self._remove(x))
        row.addWidget(del_btn)
        card.body().addLayout(row)
        return card

    def _remove(self, word: str):
        self.app.store.remove_word(word)
        self.app.wordbook_changed.emit()
        self.refresh()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出生词本", "生词本.csv", "CSV (*.csv)")
        if not path:
            return
        n = self.app.store.export_words(path)
        QMessageBox.information(self, "导出完成", "已导出 %d 个单词到：\n%s" % (n, path))


# =========================================================================== history
class HistoryPage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.selected_ids = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 24, 30, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(PageHeader("查询历史", "最近查过的词，点击可以重新查询"))
        head.addStretch(1)
        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.delete_selected)
        head.addWidget(self.delete_btn)
        clear = QPushButton("清空历史")
        clear.setObjectName("danger")
        clear.clicked.connect(self.clear)
        head.addWidget(clear)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.list_lay = QVBoxLayout(self.inner)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(6)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)
        self.refresh()

    def refresh(self):
        clear_layout(self.list_lay)
        self.selected_ids.clear()
        self._update_delete_btn()
        rows = self.app.store.history(300)
        if not rows:
            self.list_lay.addWidget(EmptyState("还没有查询记录", "查过的词会自动记在这里。", "clock"))
            self.list_lay.addStretch(1)
            return
        current_day = None
        for r in rows:
            day = time.strftime("%Y-%m-%d", time.localtime(r["ts"]))
            if day != current_day:
                current_day = day
                self.list_lay.addWidget(label(day, "section"))
                self.list_lay.addSpacing(2)
            self.list_lay.addWidget(self._row(r))
        self.list_lay.addStretch(1)

    def _row(self, r: dict) -> QWidget:
        holder = QWidget()
        outer = QHBoxLayout(holder)
        outer.setContentsMargins(2, 0, 2, 0)
        outer.setSpacing(8)
        cb = QCheckBox()
        cb.setCursor(Qt.PointingHandCursor)
        cb.setChecked(r["id"] in self.selected_ids)
        cb.stateChanged.connect(lambda state, rid=r["id"]: self._toggle_selection(rid, state))
        outer.addWidget(cb, 0, Qt.AlignVCenter)

        w = QPushButton()
        w.setObjectName("rowitem")
        w.setCursor(Qt.PointingHandCursor)
        w.setFixedHeight(44)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 0, 10, 0)
        lay.setSpacing(10)
        time_lb = label(time.strftime("%H:%M", time.localtime(r["ts"])), "faint")
        text_lb = label(r["text"], "body")
        lay.addWidget(time_lb)
        lay.addWidget(text_lb)
        if r.get("brief"):
            brief_lb = label(r["brief"][:60], "faint")
            lay.addWidget(brief_lb, 1)
        else:
            brief_lb = None
            lay.addStretch(1)
        chev = QLabel(w)
        chev.setPixmap(icons.svg_icon("chevron", theme["faint"], 14).pixmap(14, 14))
        lay.addWidget(chev, 0, Qt.AlignCenter)
        for child in (time_lb, text_lb, brief_lb, chev):
            if child is not None:
                child.setAttribute(Qt.WA_TransparentForMouseEvents)
        w.clicked.connect(lambda _=False, x=r["text"]: self.app.lookup_word(x))
        outer.addWidget(w, 1)
        return holder

    def _toggle_selection(self, rid: int, state: int):
        if state:
            self.selected_ids.add(int(rid))
        else:
            self.selected_ids.discard(int(rid))
        self._update_delete_btn()

    def _update_delete_btn(self):
        n = len(self.selected_ids)
        self.delete_btn.setText("删除选中（%d）" % n if n else "删除选中")
        self.delete_btn.setEnabled(n > 0)

    def delete_selected(self):
        if not self.selected_ids:
            return
        self.app.store.delete_history_ids(self.selected_ids)
        self.selected_ids.clear()
        self.refresh()

    def clear(self):
        if self.app.store.history(1):
            if QMessageBox.question(self, "清空历史", "确定清空全部查询历史吗？") != QMessageBox.Yes:
                return
        self.app.store.clear_history()
        self.refresh()


# =========================================================================== settings
class SettingRow(QWidget):
    def __init__(self, title: str, desc: str, control: QWidget, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 8, 0, 8)
        row.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(3)
        t = label(title, "body")
        f = t.font()
        f.setPixelSize(13.5)
        f.setWeight(QFont.DemiBold)
        t.setFont(f)
        text.addWidget(t)
        if desc:
            text.addWidget(label(desc, "faint", wrap=True))
        row.addLayout(text, 1)
        row.addWidget(control, 0, Qt.AlignVCenter)


class SettingsPage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.s = app.settings
        area, inner, lay = scroll_page()
        self.scroll = area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(area)
        lay.addWidget(PageHeader("设置", "所有选项都会立即生效"))

        # ---- 划词
        lay.addWidget(self._section_label("划词与悬浮球"))
        card = Card()
        card.body().setSpacing(0)
        card.body().addWidget(SettingRow(
            "启用划词", "选中文字后，在鼠标旁边显示一个小标志；点它才打开释义卡片",
            self._switch("selection_enabled", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "显示悬浮球", "屏幕边缘的圆形按钮，随时唤起查词窗口",
            self._switch("ball_enabled", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "在终端里也启用划词", "部分终端里发送复制可能中断正在运行的程序，默认关闭",
            self._switch("selection_in_terminals", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "恢复剪贴板", "划词后把原来的文字放回剪贴板；如果剪贴板里是图片/文件，会跳过这次划词以免覆盖",
            self._switch("restore_clipboard", card)))
        card.body().addWidget(hline())
        combo = QComboBox()
        for sec in (5, 8, 12, 20):
            combo.addItem("%d 秒" % sec, sec)
        combo.setCurrentIndex(max(0, combo.findData(self.s.get("bubble_timeout_s", 8))))
        combo.currentIndexChanged.connect(lambda: self._set("bubble_timeout_s", combo.currentData()))
        card.body().addWidget(SettingRow("气泡停留时间", "鼠标移开后气泡自动消失的时间", combo))
        card.body().addWidget(hline())
        bubble_src = QComboBox()
        for code, name in (
            ("auto", "自动：本地 → ECDICT → WordNet"),
            ("local", "仅本地词典"),
            ("ecdict", "仅 ECDICT"),
            ("wordnet", "仅 WordNet"),
            ("youdao", "在线：有道"),
            ("youdao_first", "在线优先：有道 → 无网回退 ECDICT"),
        ):
            bubble_src.addItem(name, code)
        try:
            for src in self.app.store.custom_sources():
                name = src.get("source") or "本地词库"
                bubble_src.addItem("本地 · " + name, "local:" + name)
        except Exception:
            pass
        bubble_src.setCurrentIndex(max(0, bubble_src.findData(
            self.s.get("bubble_source", "auto")
        )))
        bubble_src.currentIndexChanged.connect(
            lambda: self._set("bubble_source", bubble_src.currentData())
        )
        card.body().addWidget(SettingRow(
            "紧凑小窗来源",
            "只决定紧凑小窗优先显示哪一本；展开后的来源和顺序在下方单独设置",
            bubble_src,
        ))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "本地无结果时在线补全",
            "开启后，离线查不到时才请求有道；默认关闭，保证小窗秒开",
            self._switch("bubble_online_fallback", card),
        ))
        card.body().addWidget(hline())
        expand_row = QWidget()
        er = QHBoxLayout(expand_row)
        er.setContentsMargins(0, 0, 0, 0)
        er.setSpacing(12)
        selected = self.s.get("bubble_expand_sources")
        if not isinstance(selected, list):
            selected = ["local", "ecdict", "wordnet"]
        for code, text in (
            ("local", "本地词典"), ("ecdict", "ECDICT"),
            ("wordnet", "WordNet"), ("youdao", "有道·在线"),
        ):
            cb = QCheckBox(text)
            cb.setChecked(code in selected)
            cb.stateChanged.connect(
                lambda state, c=code: self._toggle_bubble_expand_source(c, bool(state))
            )
            er.addWidget(cb)
        er.addStretch(1)
        card.body().addWidget(SettingRow(
            "小窗展开来源",
            "只控制展开小窗；顺序在下面单独调整",
            expand_row,
        ))
        card.body().addWidget(hline())
        card.body().addWidget(label("小窗展开顺序", "faint"))
        bubble_labels = {
            "local": "本地词典",
            "ecdict": "ECDICT",
            "wordnet": "WordNet",
            "youdao": "有道 · 在线",
        }
        bubble_defaults = ["local", "ecdict", "wordnet", "youdao"]
        bubble_order = [k for k in (self.s.get("bubble_order") or []) if k in bubble_labels]
        for k in bubble_defaults:
            if k not in bubble_order:
                bubble_order.append(k)
        for key in bubble_order:
            row_widget = QWidget()
            bl = QHBoxLayout(row_widget)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            up = QPushButton("↑")
            up.setObjectName("chip")
            up.setFixedWidth(30)
            up.clicked.connect(lambda _=False, k=key: self._move_bubble_order(k, -1))
            bl.addWidget(up)
            down = QPushButton("↓")
            down.setObjectName("chip")
            down.setFixedWidth(30)
            down.clicked.connect(lambda _=False, k=key: self._move_bubble_order(k, 1))
            bl.addWidget(down)
            card.body().addWidget(SettingRow(bubble_labels[key], "", row_widget))
        lay.addWidget(card)

        # ---- 词典
        lay.addWidget(self._section_label("词典与翻译"))
        card = Card()
        card.body().setSpacing(0)
        card.body().addWidget(SettingRow(
            "中英互译", "英文词显示中文释义，中文词查英文；关闭后只保留英英释义",
            self._switch("cn_en", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "英英互译", "显示 WordNet 英文释义、例句和同义词",
            self._switch("en_en", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "在线词典增强", "联网补充有道词典的释义、例句与 Datamuse 同义词，失败时不影响离线结果",
            self._switch("online_dict", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "在线优先", "有网络时优先显示有道释义；离线词典只做兜底", self._switch("online_first", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "完整模式", "打开后释义/例句不截断；关闭时卡片保持紧凑", self._switch("full_content", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "并列显示所有来源", "「全部」时同时列出 ECDICT、WordNet、柯林斯、有道，便于对照",
            self._switch("parallel_sources", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "全文搜索", "开启后额外搜索释义和例句；关闭时完全保持原来的查词行为",
            self._switch("fulltext_enabled", card)))
        provider = QComboBox()
        for code, name in (("mymemory", "MyMemory 免费"), ("google", "Google 免费"), ("deepl", "DeepL（需 Key）")):
            provider.addItem(name, code)
        provider.setCurrentIndex(max(0, provider.findData(self.s.get("translate_provider", "mymemory"))))
        provider.currentIndexChanged.connect(self._provider_changed)
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "整句翻译服务", "划选整句时使用的翻译引擎；MyMemory 免费但每日有额度", provider))
        self.key_row = QWidget()
        key_lay = QHBoxLayout(self.key_row)
        key_lay.setContentsMargins(0, 0, 0, 0)
        self.key_edit = QLineEdit(self.s.get("translate_key", ""))
        self.key_edit.setPlaceholderText("DeepL API Key")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setFixedWidth(300)
        self.key_edit.textChanged.connect(lambda t: self._set("translate_key", t.strip()))
        key_lay.addWidget(self.key_edit)
        test = QPushButton("测试")
        test.setObjectName("chip")
        test.clicked.connect(self._test_translate)
        key_lay.addWidget(test)
        self.key_row.setVisible(self.s.get("translate_provider") == "deepl")
        card.body().addWidget(self.key_row)
        lay.addWidget(card)

        # ---- 词典来源
        lay.addWidget(self._section_label("词典来源"))
        card = Card()
        card.body().setSpacing(0)
        sources = [
            ("英汉词典 · ECDICT", "77 万英汉词条，含音标、词形变化和考试标签", "source_ecdict"),
            ("中英词典 · CC-CEDICT", "12.5 万条中英双向词条，带拼音", "source_cedict"),
            ("英英词典 · WordNet", "英文释义、例句和同义词", "source_wordnet"),
            ("在线释义 · 有道", "补充例句、网络释义和音标（需要联网）", "source_youdao"),
            ("在线同义词 · Datamuse", "补充英文同义词（需要联网）", "source_datamuse"),
        ]
        for i, (title, desc, key) in enumerate(sources):
            if i:
                card.body().addWidget(hline())
            card.body().addWidget(SettingRow(title, desc, self._switch(key, card)))
        card.body().addWidget(hline())
        exam = QComboBox()
        for code, name in (("", "不限"), ("zk", "中考"), ("gk", "高考"), ("cet4", "四级"),
                           ("cet6", "六级"), ("ky", "考研"), ("toefl", "托福"),
                           ("ielts", "雅思"), ("gre", "GRE")):
            exam.addItem(name, code)
        exam.setCurrentIndex(max(0, exam.findData(self.s.get("target_exam", ""))))
        exam.currentIndexChanged.connect(lambda: self._set("target_exam", exam.currentData()))
        card.body().addWidget(SettingRow("目标考试", "显示该词是否在词表内，并给出对应的考法例句", exam))
        card.body().addWidget(hline())
        mw1 = QLineEdit(self.s.get("mw_collegiate_key", ""))
        mw1.setPlaceholderText("Collegiate API Key")
        mw1.setFixedHeight(34)
        mw1.setFixedWidth(300)
        mw1.editingFinished.connect(lambda: self._set("mw_collegiate_key", mw1.text().strip()))
        card.body().addWidget(SettingRow("韦氏 Collegiate Key", "dictionaryapi.com 申请；留空不启用", mw1))
        card.body().addWidget(hline())
        mw2 = QLineEdit(self.s.get("mw_learners_key", ""))
        mw2.setPlaceholderText("Learner's API Key")
        mw2.setFixedHeight(34)
        mw2.setFixedWidth(300)
        mw2.editingFinished.connect(lambda: self._set("mw_learners_key", mw2.text().strip()))
        card.body().addWidget(SettingRow("韦氏 Learner's Key", "dictionaryapi.com 申请；留空不启用", mw2))
        card.body().addWidget(hline())
        mwv = QComboBox()
        for code, name in (("collegiate", "Collegiate"), ("learners", "Learner's")):
            mwv.addItem(name, code)
        mwv.setCurrentIndex(max(0, mwv.findData(self.s.get("mw_variant", "collegiate"))))
        mwv.currentIndexChanged.connect(lambda: self._set("mw_variant", mwv.currentData()))
        card.body().addWidget(SettingRow("韦氏版本", "选择用哪一部在线查询", mwv))
        lay.addWidget(card)

        # ---- 显示顺序
        lay.addWidget(self._section_label("显示顺序"))
        order_card = Card()
        labels = {
            "ecdict": "ECDICT · 离线",
            "wordnet": "WordNet · 离线",
            "local": "本地词典",
            "collins": "柯林斯 · 在线",
            "youdao": "有道 · 在线",
            "merriam": "韦氏 · 在线",
        }
        keys = [k for k in (self.s.get("source_order") or []) if k in labels]
        for k in labels:
            if k not in keys:
                keys.append(k)
        for idx, key in enumerate(keys):
            row_widget = QWidget()
            rl = QHBoxLayout(row_widget)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(6)
            up = QPushButton("↑")
            up.setObjectName("chip")
            up.setFixedWidth(30)
            up.clicked.connect(lambda _=False, k=key: self._move_source_order(k, -1))
            rl.addWidget(up)
            down = QPushButton("↓")
            down.setObjectName("chip")
            down.setFixedWidth(30)
            down.clicked.connect(lambda _=False, k=key: self._move_source_order(k, 1))
            rl.addWidget(down)
            order_card.body().addWidget(SettingRow(labels[key], "", row_widget))
        order_card.body().addWidget(hline())
        order_card.body().addWidget(SettingRow(
            "右侧栏固定",
            "开启后右侧辅助栏固定在右边；关闭后跟随整页一起滚动",
            self._switch(
                "right_fixed", order_card,
                callback=lambda _v: self.app.window.search_page.rerender(),
            ),
        ))
        order_card.body().addWidget(SettingRow(
            "左右联动滚动",
            "两边一起滚；一方到底后停住，另一方继续滚动；反向时同样",
            self._switch(
                "linked_scroll", order_card,
                callback=lambda _v: self.app.window.search_page.rerender(),
            ),
        ))
        order_card.body().addWidget(SettingRow(
            "右侧栏透明画风",
            "开启后右侧辅助栏使用透明背景；关闭后使用普通面板背景",
            self._switch(
                "right_transparent", order_card,
                callback=lambda _v: (
                    self.app.window.search_page._apply_right_style(),
                    self.app.window.search_page.rerender(),
                ),
            ),
        ))
        order_card.body().addWidget(hline())
        order_card.body().addWidget(label("右侧栏顺序", "faint"))
        right_labels = {
            "phrs": "有道搭配",
            "web": "网络释义",
            "forms": "词形变化",
            "synonyms": "同义词",
            "frequency": "词频",
        }
        right_defaults = ["phrs", "web", "forms", "synonyms", "frequency"]
        right_keys = [k for k in (self.s.get("right_order") or []) if k in right_labels]
        for k in right_defaults:
            if k not in right_keys:
                right_keys.append(k)
        for key in right_keys:
            row_widget = QWidget()
            rl = QHBoxLayout(row_widget)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(6)
            up = QPushButton("↑")
            up.setObjectName("chip")
            up.setFixedWidth(30)
            up.clicked.connect(lambda _=False, k=key: self._move_right_order(k, -1))
            rl.addWidget(up)
            down = QPushButton("↓")
            down.setObjectName("chip")
            down.setFixedWidth(30)
            down.clicked.connect(lambda _=False, k=key: self._move_right_order(k, 1))
            rl.addWidget(down)
            order_card.body().addWidget(SettingRow(right_labels[key], "", row_widget))
        order_card.body().addWidget(hline())
        reset = QPushButton("恢复默认顺序")
        reset.setObjectName("chip")
        reset.clicked.connect(self._reset_source_order)
        order_card.body().addWidget(reset, 0, Qt.AlignLeft)
        lay.addWidget(order_card)

        # ---- 本地词典
        lay.addWidget(self._section_label("本地词典"))
        card = Card()
        card.body().setSpacing(0)
        custom_row = QWidget()
        cr = QHBoxLayout(custom_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        import_btn = QPushButton("导入 CSV / JSON")
        import_btn.setObjectName("primary")
        import_btn.clicked.connect(self._import_custom)
        cr.addWidget(import_btn)
        export_btn = QPushButton("导出本地词典")
        export_btn.setObjectName("chip")
        export_btn.clicked.connect(self._export_custom)
        cr.addWidget(export_btn)
        clear_btn = QPushButton("清空本地词典")
        clear_btn.setObjectName("chip")
        clear_btn.clicked.connect(self._clear_custom)
        cr.addWidget(clear_btn)
        self.custom_count_lb = label("", "faint")
        cr.addWidget(self.custom_count_lb)
        card.body().addWidget(SettingRow(
            "导入自己的词库",
            "支持 CSV / TSV / JSON / TXT；只保存在本机 user.db，不会上传 GitHub 或 B站。"
            " MDX / LD2 需先导出为这些格式。",
            custom_row,
        ))
        sources = self.app.store.custom_sources()
        for src in sources:
            card.body().addWidget(hline())
            name = src.get("source", "本地词库")
            controls = QWidget()
            cl = QHBoxLayout(controls)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(6)
            sw = ToggleSwitch(controls, bool(src.get("enabled", 1)))
            sw.setToolTip("关闭：不参与查词，但不会删除词条")
            sw.toggled.connect(
                lambda v, n=name: self._toggle_custom_source(n, v)
            )
            cl.addWidget(sw)
            state_lb = label("启用" if src.get("enabled", 1) else "关闭", "faint")
            sw.toggled.connect(
                lambda v, lb=state_lb: lb.setText("启用" if v else "关闭")
            )
            cl.addWidget(state_lb)
            up_btn = QPushButton("↑")
            up_btn.setObjectName("chip")
            up_btn.setFixedWidth(30)
            up_btn.clicked.connect(lambda _=False, n=name: self._move_custom_source(n, -1))
            cl.addWidget(up_btn)
            down_btn = QPushButton("↓")
            down_btn.setObjectName("chip")
            down_btn.setFixedWidth(30)
            down_btn.clicked.connect(lambda _=False, n=name: self._move_custom_source(n, 1))
            cl.addWidget(down_btn)
            rename_btn = QPushButton("重命名")
            rename_btn.setObjectName("chip")
            rename_btn.clicked.connect(lambda _=False, n=name: self._rename_custom_source(n))
            cl.addWidget(rename_btn)
            del_btn = QPushButton("删除")
            del_btn.setObjectName("chip")
            del_btn.clicked.connect(lambda _=False, n=name: self._delete_custom_source(n))
            cl.addWidget(del_btn)
            card.body().addWidget(SettingRow(
                name,
                "%d 条 · 关闭后不参与查词" % int(src.get("count", 0)),
                controls,
            ))
        lay.addWidget(card)
        self._refresh_custom_count()

        # ---- 发音
        lay.addWidget(self._section_label("发音"))
        card = Card()
        card.body().setSpacing(0)
        card.body().addWidget(SettingRow(
            "系统语音（推荐）", "Windows 自带语音，点击立即朗读，不依赖网络", self._switch("tts_system", card)))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "在线真人发音（备用）", "从有道下载真人读音；系统语音不可用时才使用", self._switch("tts_online", card)))
        lay.addWidget(card)

        # ---- 数据与备份
        lay.addWidget(self._section_label("数据与备份"))
        card = Card()
        card.body().setSpacing(0)
        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        br.setSpacing(8)
        backup_btn = QPushButton("备份学习数据")
        backup_btn.setObjectName("primary")
        backup_btn.clicked.connect(self._backup_data)
        br.addWidget(backup_btn)
        restore_btn = QPushButton("恢复备份")
        restore_btn.setObjectName("chip")
        restore_btn.clicked.connect(self._restore_data)
        br.addWidget(restore_btn)
        card.body().addWidget(SettingRow(
            "备份与恢复",
            "备份生词、FSRS 复习状态和查询历史；不包含 API Key。恢复前会自动保留当前数据库副本。",
            btn_row,
        ))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "允许合并恢复",
            "开启后恢复时可选择「合并」：只补充缺失生词，保留当前 FSRS 进度；关闭时只能替换。",
            self._switch("merge_restore_enabled", card),
        ))
        lay.addWidget(card)

        # ---- 外观
        lay.addWidget(self._section_label("外观"))
        card = Card()
        card.body().setSpacing(0)
        seg_host = QWidget()
        self.seg_host = seg_host
        seg = QHBoxLayout(seg_host)
        seg.setContentsMargins(0, 0, 0, 0)
        seg.setSpacing(0)
        self.theme_group = QButtonGroup(self)
        for i, (mode, name, icon) in enumerate((
            ("system", "跟随系统", "monitor"), ("light", "浅色", "sun"), ("dark", "深色", "moon")
        )):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("seg", True)
            b.setIcon(icons.svg_icon(icon, theme["sub"], 15))
            b.setChecked(self.s.get("theme", "system") == mode)
            b.clicked.connect(lambda _=False, m=mode: self._set_theme(m))
            self.theme_group.addButton(b)
            seg.addWidget(b)
        self._seg_styles()
        card.body().addWidget(SettingRow("主题", "浅色 / 深色 / 跟随系统", seg_host))
        lay.addWidget(card)
        self._build_system_and_data(lay)

    def _seg_styles(self):
        self.seg_host.setStyleSheet(
            f"QPushButton[seg=\"true\"] {{ background:transparent;border:1px solid {theme['border']};"
            f"padding:6px 14px;color:{theme['sub']}; }}"
            f"QPushButton[seg=\"true\"]:checked {{ background:{theme['accent']};color:#fff;border-color:{theme['accent']}; }}"
        )

    def on_theme_changed(self):
        self._seg_styles()
        try:
            for b in self.theme_group.buttons():
                b.setIcon(icons.svg_icon(
                    {"跟随系统": "monitor", "浅色": "sun", "深色": "moon"}.get(b.text(), "sun"),
                    theme["sub"], 15))
        except Exception:
            pass

    def _build_system_and_data(self, lay):
        # ---- 系统
        lay.addWidget(self._section_label("启动与系统"))
        card = Card()
        card.body().setSpacing(0)
        self.autostart_switch = self._switch("autostart", card, self._autostart_changed)
        card.body().addWidget(SettingRow(
            "开机自启", "只写入当前用户的注册表启动项（HKCU），随时可以在这里关掉", self.autostart_switch))
        card.body().addWidget(hline())
        card.body().addWidget(SettingRow(
            "关闭窗口时最小化到托盘", "关闭主窗口但不退出，悬浮球和划词继续工作",
            self._switch("close_to_tray", card)))
        lay.addWidget(card)

        # ---- 数据
        lay.addWidget(self._section_label("数据"))
        card = Card()
        card.body().setSpacing(0)
        path_row = QWidget()
        pr = QHBoxLayout(path_row)
        pr.setContentsMargins(0, 0, 0, 0)
        self.path_lb = label(self.app.config_module.DATA_DIR, "faint")
        self.path_lb.setWordWrap(True)
        pr.addWidget(self.path_lb)
        open_btn = QPushButton("打开")
        open_btn.setObjectName("chip")
        open_btn.clicked.connect(self.app.open_data_dir)
        pr.addWidget(open_btn)
        card.body().addWidget(SettingRow("数据目录", "词典、缓存、生词本和设置都保存在这里", path_row))
        card.body().addWidget(hline())
        clear_tts = QPushButton("清理")
        clear_tts.setObjectName("chip")
        clear_tts.clicked.connect(self._clear_tts)
        card.body().addWidget(SettingRow("发音缓存", "离线保存的读音文件", clear_tts))
        card.body().addWidget(hline())
        stats = self.app.lexicon.stats()
        info = "%s 词条 · %s 中文词条 · %s 英文义项" % (
            f"{stats['words']:,}", f"{stats['cedict']:,}", f"{stats['synsets']:,}"
        )
        card.body().addWidget(SettingRow("离线词典", info, label("就绪" if stats["ready"] else "缺失", "ok" if stats["ready"] else "error")))
        lay.addWidget(card)

        lay.addWidget(label("划词词典 v%s · Python + PySide6 · 离线数据来自 ECDICT / CC-CEDICT / WordNet" % self.app.version, "faint"))
        lay.addStretch(1)

    # ------------------------------------------------------------------ helpers
    def _section_label(self, text: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 10, 0, 2)
        lay.addWidget(label(text, "section"))
        return w

    def _switch(self, key: str, parent, callback=None) -> ToggleSwitch:
        sw = ToggleSwitch(parent, bool(self.s.get(key)))
        def on(v):
            self._set(key, v)
            if callback:
                callback(v)
        sw.toggled.connect(on)
        return sw

    def _refresh_custom_count(self):
        try:
            n = self.app.store.custom_count()
        except Exception:
            n = 0
        self.custom_count_lb.setText("已导入 %d 条" % n if n else "还没有导入")

    def _toggle_custom_source(self, source: str, enabled: bool):
        try:
            self.app.store.set_custom_source_enabled(source, enabled)
            page = self.app.window.search_page
            query = page.search_box.text().strip()
            if query:
                page.search(query)
        except Exception:
            pass

    def _move_custom_source(self, source: str, delta: int):
        if self.app.store.move_custom_source(source, delta):
            self._refresh_search()
            QTimer.singleShot(0, self.app.window.refresh_settings)

    def _rename_custom_source(self, source: str):
        new, ok = QInputDialog.getText(
            self, "重命名本地词典", "新的来源名称：", text=source
        )
        if not ok:
            return
        new = new.strip()
        if not new or new == source:
            return
        n = self.app.store.rename_custom_source(source, new)
        if n < 0:
            QMessageBox.warning(self, "重命名失败", "这个名称已经存在，请换一个。")
            return
        self._refresh_search()
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _delete_custom_source(self, source: str):
        if QMessageBox.question(
            self,
            "删除本地词典",
            "确定删除「%s」的全部词条吗？\n不会影响其他来源。" % source,
        ) != QMessageBox.Yes:
            return
        self.app.store.delete_custom_source(source)
        self._refresh_search()
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _refresh_search(self):
        page = self.app.window.search_page
        query = page.search_box.text().strip()
        if query:
            page.search(query)

    def _import_custom(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入本地词典",
            "",
            "词典文件 (*.csv *.tsv *.json *.txt);;所有文件 (*)",
        )
        if not path:
            return
        try:
            entries = parse_custom_dictionary(path)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if not entries:
            QMessageBox.warning(self, "导入失败", "文件里没有识别到词条。")
            return
        n = self.app.store.add_custom_entries(entries, os.path.basename(path))
        self._refresh_custom_count()
        QMessageBox.information(
            self,
            "导入完成",
            "已导入 %d 条词条，只保存在本机。\n文件：%s" % (n, os.path.basename(path)),
        )
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _export_custom(self):
        default = os.path.join(
            os.path.dirname(self.app.store.path),
            "local-dict-" + time.strftime("%Y%m%d-%H%M%S") + ".json",
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出本地词典", default, "JSON (*.json);;所有文件 (*)"
        )
        if not path:
            return
        try:
            n = self.app.store.export_custom(path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self,
            "导出完成",
            "已导出 %d 条本地词条到：\n%s\n\n"
            "文件可能包含商业词典内容，请只在本机使用，不要上传。" % (n, path),
        )

    def _clear_custom(self):
        try:
            n = self.app.store.custom_count()
        except Exception:
            n = 0
        if not n:
            QMessageBox.information(self, "本地词典", "还没有导入词条。")
            return
        if QMessageBox.question(
            self,
            "清空本地词典",
            "确定删除本机导入的 %d 条词条吗？\n不会影响 ECDICT / WordNet / CC-CEDICT。" % n,
        ) != QMessageBox.Yes:
            return
        self.app.store.clear_custom()
        self._refresh_custom_count()
        QMessageBox.information(self, "已清空", "本机导入的词条已删除。")
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _backup_data(self):
        default = os.path.join(
            os.path.dirname(self.app.store.path),
            "backup-" + time.strftime("%Y%m%d-%H%M%S") + ".json",
        )
        path, _ = QFileDialog.getSaveFileName(self, "备份学习数据", default, "JSON 备份 (*.json)")
        if not path:
            return
        try:
            counts = self.app.store.export_backup(path)
        except Exception as exc:
            QMessageBox.warning(self, "备份失败", str(exc))
            return
        QMessageBox.information(
            self, "备份完成",
            "已备份 %d 个生词、%d 条历史记录。\n\n%s" % (counts["words"], counts["history"], path),
        )

    def _restore_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "恢复备份", os.path.dirname(self.app.store.path), "JSON 备份 (*.json)")
        if not path:
            return
        try:
            info = self.app.store.inspect_backup(path)
        except Exception as exc:
            QMessageBox.warning(self, "恢复失败", "备份未通过校验或无法读取：\n%s" % exc)
            return
        summary = (
            "备份包含 %d 个生词、%d 条历史记录。\n"
            "当前已有 %d 个同名生词，可新增 %d 个。\n\n"
            "恢复前会自动保留当前数据库副本。"
            % (info["words"], info["history"], info["overlap"], info["new_words"])
        )
        mode = "replace"
        if self.s.get("merge_restore_enabled", False):
            box = QMessageBox(self)
            box.setWindowTitle("恢复备份")
            box.setText(summary)
            box.setInformativeText("请选择恢复方式：")
            replace_btn = box.addButton("替换恢复", QMessageBox.AcceptRole)
            merge_btn = box.addButton("合并恢复", QMessageBox.ActionRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is replace_btn:
                mode = "replace"
            elif clicked is merge_btn:
                mode = "merge"
            else:
                return
        else:
            if QMessageBox.question(
                self, "恢复备份",
                summary + "\n\n当前未开启「允许合并恢复」，将替换当前生词本和历史。确定继续吗？",
            ) != QMessageBox.Yes:
                return
        try:
            counts = self.app.store.import_backup(path, mode=mode)
        except Exception as exc:
            QMessageBox.warning(self, "恢复失败", "备份未通过校验或无法读取：\n%s" % exc)
            return
        self.app.window.wordbook_page.refresh()
        self.app.window.history_page.refresh()
        self.app.update_ball_badge()
        if mode == "merge":
            text = "已合并：新增 %d 个生词、%d 条历史记录；同名生词保留当前进度。" % (
                counts["added_words"], counts["added_history"])
        else:
            text = "已替换：恢复 %d 个生词、%d 条历史记录。" % (counts["words"], counts["history"])
        QMessageBox.information(self, "恢复完成", text)

    def _toggle_bubble_expand_source(self, key: str, enabled: bool):
        selected = self.s.get("bubble_expand_sources")
        if not isinstance(selected, list):
            selected = ["local", "ecdict", "wordnet"]
        selected = [k for k in selected if k != key]
        if enabled:
            selected.append(key)
        self._set("bubble_expand_sources", selected)

    def _reset_source_order(self):
        defaults = ["ecdict", "local", "wordnet", "collins", "youdao", "merriam"]
        self._set("source_order", defaults)
        self._set("right_order", ["phrs", "web", "forms", "synonyms", "frequency"])
        self._set("bubble_order", ["local", "ecdict", "wordnet", "youdao"])
        self.app.window.search_page.rerender()
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _move_bubble_order(self, key: str, delta: int):
        defaults = ["local", "ecdict", "wordnet", "youdao"]
        order = [k for k in (self.s.get("bubble_order") or []) if k in defaults]
        for k in defaults:
            if k not in order:
                order.append(k)
        if key not in order:
            return
        i = order.index(key)
        j = max(0, min(len(order) - 1, i + delta))
        if i == j:
            return
        order[i], order[j] = order[j], order[i]
        self._set("bubble_order", order)
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _move_right_order(self, key: str, delta: int):
        defaults = ["phrs", "web", "forms", "synonyms", "frequency"]
        order = [k for k in (self.s.get("right_order") or []) if k in defaults]
        for k in defaults:
            if k not in order:
                order.append(k)
        if key not in order:
            return
        i = order.index(key)
        j = max(0, min(len(order) - 1, i + delta))
        if i == j:
            return
        order[i], order[j] = order[j], order[i]
        self._set("right_order", order)
        self.app.window.search_page.rerender()
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _move_source_order(self, key: str, delta: int):
        defaults = ["ecdict", "local", "wordnet", "collins", "youdao", "merriam"]
        order = [k for k in (self.s.get("source_order") or []) if k in defaults]
        for k in defaults:
            if k not in order:
                order.append(k)
        if key not in order:
            return
        i = order.index(key)
        j = max(0, min(len(order) - 1, i + delta))
        if i == j:
            return
        order[i], order[j] = order[j], order[i]
        self._set("source_order", order)
        self.app.window.search_page.rerender()
        QTimer.singleShot(0, self.app.window.refresh_settings)

    def _set(self, key: str, value):
        self.app.set_setting(key, value)
        self.s = self.app.settings

    def _set_theme(self, mode: str):
        self._set("theme", mode)

    def _provider_changed(self, idx: int):
        code = self.sender().itemData(idx)
        self._set("translate_provider", code)
        self.key_row.setVisible(code == "deepl")

    def _autostart_changed(self, on: bool):
        ok, msg = self.app.set_autostart(on)
        if not ok:
            self.autostart_switch.blockSignals(True)
            self.autostart_switch.setChecked(not on)
            self.autostart_switch.blockSignals(False)
            QMessageBox.warning(self, "开机自启", msg)

    def _clear_tts(self):
        n = self.app.clear_tts_cache()
        QMessageBox.information(self, "清理完成", "已删除 %d 个发音缓存文件。" % n)

    def _test_translate(self):
        result = self.app.test_translate()
        QMessageBox.information(self, "翻译测试", result)
