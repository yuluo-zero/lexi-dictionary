# -*- coding: utf-8 -*-
"""Query classification, offline lookup and the async online layer."""
from __future__ import annotations

import re

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import online
from .lexicon import Lexicon, has_cjk

SENTENCE_PUNCT = re.compile(r"[。！？!?；;…]|\.\s|,\s")

# British/American spelling pairs used only for a second online attempt.
_SPELLING_PAIRS = (
    ("isation", "ization"), ("isations", "izations"),
    ("ising", "izing"), ("ised", "ized"), ("ises", "izes"), ("ise", "ize"),
    ("ization", "isation"), ("izations", "isations"),
    ("izing", "ising"), ("ized", "ised"), ("izes", "ises"), ("ize", "ise"),
)


def spelling_variants(text: str) -> list[str]:
    """Return plausible British/American spelling alternatives."""
    low = text.lower()
    out = []
    for a, b in _SPELLING_PAIRS:
        if low.endswith(a):
            alt = text[: -len(a)] + b
            if alt.lower() != low and alt.lower() not in [x.lower() for x in out]:
                out.append(alt)
    return out


def classify(text: str) -> str:
    s = text.strip()
    if not s:
        return "empty"
    if has_cjk(s):
        cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", s))
        if cjk_count <= 12 and not SENTENCE_PUNCT.search(s) and " " not in s:
            return "zh"
        return "sentence"
    if re.fullmatch(r"[A-Za-z][A-Za-z'’.\- ]{0,45}", s) and len(s.split()) <= 5:
        return "en"
    return "sentence"


def brief_of(result: dict) -> str:
    entry = result.get("entry")
    if entry:
        groups = entry.get("pos", {}).get("groups") or []
        if groups:
            return groups[0][2].split("；")[0].split(";")[0][:80]
        other = entry.get("pos", {}).get("other") or []
        if other:
            return other[0][:80]
    for item in result.get("cedict") or []:
        if item.get("glosses"):
            return min(item["glosses"], key=len)[:80]
    for item in result.get("wordnet") or []:
        return item.get("definition", "")[:80]
    trans = result.get("translation") or {}
    if trans.get("text"):
        return trans["text"][:80]
    return ""


class _Signals(QObject):
    done = Signal(int, dict)


class _OnlineJob(QRunnable):
    def __init__(self, token: int, fn, signals: _Signals):
        super().__init__()
        self.token = token
        self.fn = fn
        self.signals = signals

    def run(self):
        try:
            data = self.fn()
        except Exception as exc:  # pragma: no cover - network guard
            data = {"error": str(exc)}
        try:
            self.signals.done.emit(self.token, data)
        except RuntimeError:
            pass


class SearchEngine(QObject):
    local_ready = Signal(dict)
    online_ready = Signal(dict)

    def __init__(self, lexicon: Lexicon, settings_getter, parent=None):
        super().__init__(parent)
        self.lex = lexicon
        self.settings = settings_getter
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self._token = 0
        self._signals = _Signals()
        self._signals.done.connect(self._on_online)

    def search(self, text: str, want_online: bool = True):
        text = (text or "").strip()
        if not text:
            return
        self._token += 1
        token = self._token
        result = self._local(text)
        result["token"] = token
        self.local_ready.emit(result)
        if want_online and self.settings().get("online_dict", True):
            job = _OnlineJob(token, lambda: self._online(text, result), self._signals)
            self.pool.start(job)

    # ------------------------------------------------------------------ local
    def _local(self, text: str) -> dict:
        kind = classify(text)
        res = {
            "query": text,
            "kind": kind,
            "entry": None,
            "meta": {},
            "wordnet": [],
            "cedict": [],
            "reverse": [],
            "suggestions": [],
            "translation": None,
            "online": None,
            "error": "",
        }
        settings = self.settings()
        full = bool(settings.get("full_content", False))
        if kind == "en":
            if settings.get("source_ecdict", True):
                entry, meta = self.lex.lookup_word(text)
                res["entry"] = entry
                res["meta"] = meta
            if settings.get("source_wordnet", True):
                res["wordnet"] = self.lex.lookup_wordnet(text, limit=100 if full else 10)
            if not res["entry"] and not res["wordnet"]:
                base = re.sub(r"['’’]s$", "", text).strip()
                candidates = []
                if base and base.lower() != text.lower():
                    candidates.append(base)
                    base_entry, _ = self.lex.lookup_word(base)
                    if base_entry:
                        candidates.extend(word for _, word in (base_entry.get("exchange") or []))
                candidates.extend(self.lex.suggestions(base or text))
                seen, unique = set(), []
                for word in candidates:
                    key = word.lower()
                    if key not in seen:
                        seen.add(key)
                        unique.append(word)
                res["suggestions"] = unique[:8]
        elif kind == "zh":
            if settings.get("source_cedict", True):
                res["cedict"] = self.lex.lookup_chinese(text, limit=100 if full else 8)
            if not res["cedict"]:
                res["reverse"] = self.lex.reverse_by_chinese(text)
                res["suggestions"] = self.lex.chinese_suggestions(text[:2])
        res["brief"] = brief_of(res)
        return res

    # ------------------------------------------------------------------ online
    def _online(self, text: str, local: dict) -> dict:
        settings = self.settings()
        full = bool(settings.get("full_content", False))
        kind = local["kind"]
        out = {"dictionary": None, "youdao": None, "synonyms": [], "translation": None, "merriam": None, "error": ""}
        try:
            if kind == "en" and settings.get("online_dict", True):
                variants = spelling_variants(text)
                # Prefer an online variant that has a Collins entry.  The base
                # query may be a valid British spelling but missing from the
                # Collins/Webster data sets, which are American-leaning.
                youdao = online.youdao_lookup(text, full=full) if settings.get("source_youdao", True) else None
                used_variant = ""
                if settings.get("source_youdao", True) and not (youdao or {}).get("collins"):
                    for alt in variants:
                        if not self.lex.lookup_word(alt)[0]:
                            continue
                        alt_data = online.youdao_lookup(alt, full=full)
                        if (alt_data or {}).get("collins"):
                            youdao = alt_data
                            used_variant = alt
                            break
                out["youdao"] = youdao
                if not youdao:
                    out["dictionary"] = online.dictionary_api(text)
                if settings.get("source_datamuse", True):
                    out["synonyms"] = online.datamuse_synonyms(used_variant or text)
                variant = settings.get("mw_variant", "collegiate")
                mw_key = settings.get("mw_collegiate_key" if variant == "collegiate" else "mw_learners_key", "")
                if mw_key:
                    mw = online.merriam_lookup(used_variant or text, mw_key, variant)
                    if not (mw or {}).get("entries"):
                        for alt in variants:
                            if not self.lex.lookup_word(alt)[0]:
                                continue
                            alt_mw = online.merriam_lookup(alt, mw_key, variant)
                            if (alt_mw or {}).get("entries"):
                                mw = alt_mw
                                used_variant = used_variant or alt
                                break
                    out["merriam"] = mw
                if used_variant:
                    out["lookup_variant"] = used_variant
            elif settings.get("cn_en", True) and (
                kind == "sentence" or (kind == "zh" and not local["cedict"] and not local["reverse"])
            ):
                out["translation"] = online.translate(text, settings)
        except Exception as exc:
            out["error"] = str(exc)
        return out

    def _on_online(self, token: int, data: dict):
        if token != self._token:
            return
        self.online_ready.emit(data)
