# -*- coding: utf-8 -*-
"""Import user-provided local dictionaries (CSV / TSV / JSON / TXT).

The data stays in the local user database.  Proprietary formats such as
MDict (.mdx) and ABBYY Lingvo (.ld2) need their own parsers and are
deliberately not accepted here.
"""
from __future__ import annotations

import csv
import json
import os

_WORD_KEYS = ("word", "term", "headword", "entry", "词条", "单词")
_TRANS_KEYS = ("translation", "meaning", "chinese", "zh", "释义", "中文", "解释")
_DEF_KEYS = ("definition", "english", "en", "英文释义", "定义")
_PHON_KEYS = ("phonetic", "ipa", "音标", "发音")


def _pick(row: dict, keys) -> str:
    for key in keys:
        for k in (key, key.title(), key.upper()):
            v = row.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


def _normalise(word: str, phonetic: str, translation: str, definition: str,
               source: str = "", enabled=1) -> dict | None:
    word = (word or "").strip()
    translation = (translation or "").strip()
    definition = (definition or "").strip()
    if not word or not (translation or definition):
        return None
    if len(word) > 120:
        return None
    return {
        "word": word,
        "phonetic": (phonetic or "").strip()[:80],
        "translation": translation[:4000],
        "definition": definition[:50000],
        "source": (source or "").strip()[:120],
        "enabled": 1 if enabled else 0,
    }


def _from_rows(rows) -> list[dict]:
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _normalise(
            _pick(row, _WORD_KEYS),
            _pick(row, _PHON_KEYS),
            _pick(row, _TRANS_KEYS),
            _pick(row, _DEF_KEYS),
            str(row.get("source") or "").strip(),
            row.get("enabled", 1),
        )
        if item:
            out.append(item)
    return out


def _parse_csv(path: str, delimiter: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        rows = list(reader)
    if rows and any(k in (rows[0] or {}) for k in _WORD_KEYS):
        return _from_rows(rows)

    # Headerless CSV/TSV: word, phonetic, translation, definition
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for line in csv.reader(f, delimiter=delimiter):
            if not line or not line[0].strip():
                continue
            vals = (line + ["", "", ""])[:4]
            item = _normalise(vals[0], vals[1], vals[2], vals[3])
            if item:
                out.append(item)
    return out


def _parse_json(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, list):
        return _from_rows(data)
    if isinstance(data, dict):
        # Own export format: {"custom": [{...}, ...]}
        if isinstance(data.get("custom"), list):
            return _from_rows(data["custom"])
        # Either one entry, or {"word": "translation", ...}
        if any(k in data for k in _WORD_KEYS):
            return _from_rows([data])
        out = []
        for word, value in data.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("word", word)
                out.extend(_from_rows([row]))
            elif isinstance(value, str) and value.strip():
                item = _normalise(word, "", value, "")
                if item:
                    out.append(item)
        return out
    return []


def _parse_txt(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" in line:
                parts = line.split("\t")
            elif "|" in line:
                parts = line.split("|")
            elif "=" in line:
                left, right = line.split("=", 1)
                parts = [left, "", right]
            else:
                continue
            vals = (parts + ["", "", ""])[:4]
            item = _normalise(vals[0], vals[1], vals[2], vals[3])
            if item:
                out.append(item)
    return out


def parse_custom_dictionary(path: str) -> list[dict]:
    """Parse a user-provided dictionary file.

    Raises ValueError with a user-facing message for unsupported formats.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mdx", ".mdd", ".ld2", ".ldx"):
        raise ValueError(
            "暂不支持 .mdx / .ld2 专有格式。\n"
            "请先用词典软件导出为 CSV、TSV、JSON 或 TXT，再导入。"
        )
    if ext == ".csv":
        return _parse_csv(path, ",")
    if ext == ".tsv":
        return _parse_csv(path, "\t")
    if ext == ".json":
        return _parse_json(path)
    if ext == ".txt":
        return _parse_txt(path)
    raise ValueError("只支持 CSV、TSV、JSON、TXT 文件。")
