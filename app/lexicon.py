# -*- coding: utf-8 -*-
"""Offline dictionary access: ECDICT, CC-CEDICT, WordNet."""
from __future__ import annotations

import os
import re
import sqlite3
import threading

TAG_NAMES = {
    "zk": "中考", "gk": "高考", "cet4": "四级", "cet6": "六级", "ky": "考研",
    "toefl": "托福", "ielts": "雅思", "gre": "GRE",
}

POS_NAMES = {
    "n": "名词", "v": "动词", "vt": "及物动词", "vi": "不及物动词", "adj": "形容词",
    "adv": "副词", "prep": "介词", "pron": "代词", "conj": "连词", "num": "数词",
    "art": "冠词", "int": "感叹词", "aux": "助动词", "abbr": "缩写", "pref": "前缀",
    "suf": "后缀", "phr": "短语", "a": "形容词",
}

WN_POS = {"n": "名词", "v": "动词", "a": "形容词", "s": "形容词", "r": "副词"}

EXCHANGE_LABELS = {
    "p": "过去式", "d": "过去分词", "i": "现在分词", "3": "第三人称单数",
    "r": "比较级", "t": "最高级", "s": "复数", "0": "原形",
}

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def _tone_mark(syllable: str) -> str:
    """Convert a numbered pinyin syllable (ni3) into tone marks (nǐ)."""
    m = re.match(r"^([a-zA-Zü:]+)([0-5])?$", syllable)
    if not m:
        return syllable
    body, tone = m.group(1), m.group(2) or "5"
    body = body.replace("u:", "ü").replace("v", "ü")
    if tone == "5" or tone == "0":
        return body
    idx = int(tone) - 1
    marks = {
        "a": "āáǎà", "o": "ōóǒò", "e": "ēéěè", "i": "īíǐì",
        "u": "ūúǔù", "ü": "ǖǘǚǜ",
    }
    lower = body.lower()
    target = None
    if "a" in lower:
        target = "a"
    elif "e" in lower:
        target = "e"
    elif "ou" in lower:
        target = "o"
    else:
        for ch in reversed(lower):
            if ch in "aeiouü":
                target = ch
                break
    if target is None:
        return body
    pos = lower.rfind(target)
    marked = marks[target][idx]
    if body[pos].isupper():
        marked = marked.upper()
    return body[:pos] + marked + body[pos + 1:]


def pretty_pinyin(pinyin: str) -> str:
    return " ".join(_tone_mark(s) for s in pinyin.split())


def pretty_phonetic(phonetic: str) -> str:
    """ECDICT stores stress as ASCII ' and , - render proper IPA marks."""
    if not phonetic:
        return ""
    p = phonetic.strip().strip("/")
    p = p.replace("'", "ˈ").replace(",", "ˌ")
    p = p.replace("ә", "ə").replace("ɡ", "g")
    return p


class Lexicon:
    def __init__(self, dict_dir: str):
        self.dir = dict_dir
        self.lock = threading.RLock()
        self.ecdict = self._connect(os.path.join(dict_dir, "ecdict.db"))
        self.cedict = self._connect(os.path.join(dict_dir, "cedict.db"))
        self.wordnet = self._connect(os.path.join(dict_dir, "wordnet.db"))

    @staticmethod
    def _connect(path):
        if not os.path.exists(path):
            return None
        uri = "file:%s?mode=ro" % path.replace("\\", "/").replace(" ", "%20")
        con = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA case_sensitive_like=ON")
            con.execute("PRAGMA query_only=ON")
        except sqlite3.Error:
            pass
        return con

    # ------------------------------------------------------------------ ECDICT
    def _ecdict_rows(self, word: str):
        if not self.ecdict:
            return []
        with self.lock:
            cur = self.ecdict.execute("SELECT * FROM words WHERE lword=? LIMIT 4", (word.lower(),))
            rows = cur.fetchall()
        return rows

    def _ecdict_form_bases(self, word: str):
        if not self.ecdict:
            return []
        with self.lock:
            cur = self.ecdict.execute("SELECT base FROM forms WHERE form=? LIMIT 6", (word.lower(),))
            return [r["base"] for r in cur.fetchall()]

    def lookup_word(self, word: str):
        """Return (entry, meta) for an English word/phrase."""
        word = word.strip()
        if not word:
            return None, {}
        rows = self._ecdict_rows(word)
        base = None
        if not rows:
            for b in self._ecdict_form_bases(word):
                rows = self._ecdict_rows(b)
                if rows:
                    base = b
                    break
        if not rows:
            return None, {}
        row = max(rows, key=lambda r: (r["collins"], r["oxford"], -r["frq"] or -999999))
        translation = (row["translation"] or "").replace("\\n", "\n")
        definition = (row["definition"] or "").replace("\\n", "\n")
        entry = {
            "word": row["word"],
            "phonetic": pretty_phonetic(row["phonetic"] or ""),
            "translation": translation,
            "definition": definition,
            "tags": [TAG_NAMES[t] for t in (row["tag"] or "").split() if t in TAG_NAMES],
            "collins": row["collins"] or 0,
            "oxford": bool(row["oxford"]),
            "bnc": row["bnc"] or 0,
            "frq": row["frq"] or 0,
            "pos": self._parse_pos(translation),
            "exchange": self._parse_exchange(row["exchange"] or "", row["word"]),
            "audio": row["audio"] or "",
        }
        meta = {}
        if base and base.lower() != word.lower():
            meta["base"] = base
        return entry, meta

    @staticmethod
    def _parse_pos(translation: str):
        groups = []
        network = []
        other = []
        for raw in translation.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("[网络]"):
                network.append(line.replace("[网络]", "").strip())
                continue
            m = re.match(r"^([a-zA-Z]{1,6})\.\s*(.+)$", line)
            if m:
                code = m.group(1).lower()
                groups.append((code, POS_NAMES.get(code, m.group(1) + "."), m.group(2).strip()))
            else:
                other.append(line)
        return {"groups": groups, "network": network, "other": other}

    @staticmethod
    def _parse_exchange(exchange: str, word: str):
        out = []
        for part in exchange.split("/"):
            if ":" not in part:
                continue
            code, vals = part.split(":", 1)
            code = code.strip()
            if code not in EXCHANGE_LABELS or not vals.strip():
                continue
            for v in vals.split(","):
                v = v.strip()
                if v and v.lower() != word.lower():
                    out.append((EXCHANGE_LABELS[code], v))
        return out

    def suggestions(self, prefix: str, limit: int = 8):
        if not self.ecdict:
            return []
        prefix = prefix.strip().lower()
        if not prefix:
            return []
        with self.lock:
            cur = self.ecdict.execute(
                "SELECT word, frq FROM words WHERE lword LIKE ? AND lword<>? "
                "ORDER BY (frq=0), frq, collins DESC LIMIT ?",
                (prefix.replace("%", "\\%").replace("_", "\\_") + "%", prefix, limit),
            )
            return [r["word"] for r in cur.fetchall()]

    def reverse_by_chinese(self, text: str, limit: int = 6):
        """Fallback ZH->EN using ECDICT translation column."""
        if not self.ecdict:
            return []
        with self.lock:
            cur = self.ecdict.execute(
                "SELECT word, phonetic, translation FROM words WHERE translation LIKE ? "
                "ORDER BY (frq=0), frq LIMIT ?",
                ("%" + text + "%", limit),
            )
            return [
                {"word": r["word"], "phonetic": r["phonetic"] or "", "translation": r["translation"] or ""}
                for r in cur.fetchall()
            ]

    # ------------------------------------------------------------------ CEDICT
    def lookup_chinese(self, text: str, limit: int = 8):
        if not self.cedict:
            return []
        text = text.strip()
        with self.lock:
            cur = self.cedict.execute(
                "SELECT trad,simp,pinyin,gloss FROM entries WHERE simp=? OR trad=? LIMIT ?",
                (text, text, limit),
            )
            rows = cur.fetchall()
            if not rows and len(text) <= 8:
                cur = self.cedict.execute(
                    "SELECT trad,simp,pinyin,gloss FROM entries WHERE simp LIKE ? LIMIT ?",
                    (text + "%", limit),
                )
                rows = cur.fetchall()
        out = []
        seen = {}
        for r in rows:
            glosses = [g.strip() for g in (r["gloss"] or "").split("\n") if g.strip()]
            glosses = [g for g in glosses if not g.upper().startswith("CL:")]
            key = (r["simp"], r["trad"])
            py = pretty_pinyin(r["pinyin"] or "")
            if key in seen:
                e = seen[key]
                for g in glosses:
                    if g not in e["glosses"]:
                        e["glosses"].append(g)
                if e["pinyin"][:1].isupper() and py[:1].islower():
                    e["pinyin"] = py
                continue
            e = {"trad": r["trad"], "simp": r["simp"], "pinyin": py, "glosses": glosses}
            seen[key] = e
            out.append(e)
        return out

    def fulltext_search(self, text: str, limit: int = 15):
        """Search definitions/translations, not just headwords."""
        q = (text or "").strip()
        if len(q) < 2:
            return []
        like = "%" + q + "%"
        out, seen = [], set()

        def add(word, source, snippet):
            word = (word or "").strip()
            key = word.lower()
            if not word or key in seen:
                return
            seen.add(key)
            out.append({"word": word, "source": source, "snippet": (snippet or "").replace("\\n", " ").strip()[:160]})

        with self.lock:
            if self.ecdict:
                rows = self.ecdict.execute(
                    "SELECT word,translation,definition FROM words "
                    "WHERE translation LIKE ? OR definition LIKE ? LIMIT ?",
                    (like, like, limit * 2),
                ).fetchall()
                for r in rows:
                    add(r["word"], "ECDICT", r["translation"] or r["definition"])
            if self.cedict:
                rows = self.cedict.execute(
                    "SELECT simp,gloss FROM entries WHERE gloss LIKE ? LIMIT ?", (like, limit)
                ).fetchall()
                for r in rows:
                    add(r["simp"], "CC-CEDICT", r["gloss"])
            if self.wordnet:
                rows = self.wordnet.execute(
                    "SELECT se.word,s.definition FROM senses se JOIN synsets s ON s.id=se.synset_id "
                    "WHERE s.definition LIKE ? LIMIT ?", (like, limit)
                ).fetchall()
                for r in rows:
                    add(r["word"], "WordNet", r["definition"])
        return out[:limit]

    def chinese_suggestions(self, prefix: str, limit: int = 8):
        if not self.cedict:
            return []
        with self.lock:
            cur = self.cedict.execute(
                "SELECT simp FROM entries WHERE simp LIKE ? GROUP BY simp LIMIT ?",
                (prefix + "%", limit),
            )
            return [r["simp"] for r in cur.fetchall()]

    # ------------------------------------------------------------------ WordNet
    def lookup_wordnet(self, word: str, limit: int = 10):
        if not self.wordnet:
            return []
        w = word.strip().lower()
        with self.lock:
            cur = self.wordnet.execute(
                "SELECT s.id,s.pos,s.definition,s.examples,se.rank FROM senses se "
                "JOIN synsets s ON s.id=se.synset_id WHERE se.word=? "
                "ORDER BY (se.rank=0), se.rank, s.id LIMIT ?",
                (w, limit),
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                cur2 = self.wordnet.execute(
                    "SELECT word FROM senses WHERE synset_id=? AND word<>? LIMIT 8", (r["id"], w)
                )
                out.append(
                    {
                        "pos": WN_POS.get(r["pos"], r["pos"]),
                        "definition": r["definition"] or "",
                        "examples": [e for e in (r["examples"] or "").split("\n") if e],
                        "synonyms": [x["word"] for x in cur2.fetchall()],
                    }
                )
        return out

    def wordnet_synonyms(self, word: str, limit: int = 12):
        w = word.strip().lower()
        if not self.wordnet:
            return []
        with self.lock:
            cur = self.wordnet.execute(
                "SELECT DISTINCT s2.word FROM senses se JOIN senses s2 ON s2.synset_id=se.synset_id "
                "WHERE se.word=? AND s2.word<>? LIMIT ?",
                (w, w, limit),
            )
            return [r["word"] for r in cur.fetchall()]

    # ------------------------------------------------------------------ stats
    def stats(self):
        out = {"words": 0, "cedict": 0, "synsets": 0, "ready": False}
        try:
            with self.lock:
                if self.ecdict:
                    out["words"] = self.ecdict.execute("SELECT count(*) FROM words").fetchone()[0]
                if self.cedict:
                    out["cedict"] = self.cedict.execute("SELECT count(*) FROM entries").fetchone()[0]
                if self.wordnet:
                    out["synsets"] = self.wordnet.execute("SELECT count(*) FROM synsets").fetchone()[0]
            out["ready"] = bool(self.ecdict and self.cedict and self.wordnet)
        except sqlite3.Error:
            pass
        return out
