# -*- coding: utf-8 -*-
"""Structured rendering for imported LD2 dictionaries.

The plain-text importer is kept for CSV/TXT.  LD2 entries get a compact JSON
payload so the UI can show sense headings, examples and etymology separately
instead of one long wall of text.
"""
from __future__ import annotations

import html
import json
import re

PREFIX = "@@LEXI2@@"


def encode(data: dict) -> str:
    return PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def decode(text: str) -> dict | None:
    text = text or ""
    if not text.startswith(PREFIX):
        return None
    try:
        data = json.loads(text[len(PREFIX):])
        return data if isinstance(data, dict) and data.get("v") == 2 else None
    except Exception:
        return None


def _clean(raw: str) -> str:
    raw = raw or ""
    raw = raw.replace("<![CDATA[", "").replace("]]>", "")
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</?(?:p|div|li|tr|h[1-4])[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(raw).replace("\xa0", " ").replace("\u3000", " ")
    text = re.sub(r"\s*·\s*", "·", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = text.replace("【 ", "【").replace(" 】", "】")
    return text.strip()


def _title(raw: str) -> str:
    text = _clean(raw).strip()
    if text.startswith("【") and text.endswith("】"):
        text = text[1:-1].strip()
    return text


def _first(pattern: str, raw: str, flags=re.S) -> str:
    m = re.search(pattern, raw, flags)
    return _clean(m.group(1)) if m else ""


def _remove_all(text: str, pieces) -> str:
    for piece in sorted({p for p in pieces if p}, key=len, reverse=True):
        text = text.replace(piece, "\n")
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_longman(xmls, word: str) -> dict | None:
    raw = "".join(xmls or [])
    if "<hr/>" in raw:
        head_raw, rest = raw.split("<hr/>", 1)
        if "<hr/>" in rest:
            index_raw, body = rest.split("<hr/>", 1)
        else:
            index_raw, body = "", rest
    elif "<br/>" in raw:
        head_raw, body = raw.split("<br/>", 1)
        index_raw = ""
    else:
        return None

    head = _clean(head_raw)
    phon = ""
    m = re.search(r"/([^/]+)/", head)
    if m:
        phon = m.group(1).strip()
    pos = ""
    tail = head[m.end():] if m else head
    m = re.search(r"\b(n|v|adj|adv|prep|conj|pron|det|excl|modal|number)\b", tail)
    if m:
        pos = m.group(1)

    index = []
    for item in re.findall(r"<b>(.*?)</b>", index_raw, re.S):
        title = _title(item)
        if title:
            index.append(title)

    parts = re.split(r"<Ë[^>]*i_(\d+)\.png[^>]*/>", body)
    etym_raw = parts[0] if parts else ""
    etym = _clean(etym_raw).strip()
    if etym.startswith("[") and etym.endswith("]"):
        etym = etym[1:-1].strip()
    if not re.search(r"Date:|Origin:|Language:", etym, re.I):
        etym = ""

    senses = []
    for idx in range(1, len(parts), 2):
        block = parts[idx + 1] if idx + 1 < len(parts) else ""
        if not block.strip():
            continue
        examples = [_clean(x) for x in re.findall(
            r'<font[^>]*color="#004080"[^>]*>(.*?)</font>', block, re.S
        )]
        examples = [x for x in examples if x]
        title = ""
        tm = re.search(r"<b>\s*(【.*?】)\s*</b>", block, re.S)
        if tm:
            title = _title(tm.group(1))
        gram = _first(r'<font[^>]*color="#009999"[^>]*>(.*?)</font>', block)
        plain = _clean(block)
        plain = _remove_all(plain, examples + [title, gram])
        plain = re.sub(r"【\s*】", "", plain)
        plain = re.sub(r"^\s*[\]\)】]+\s*", "", plain)
        lines = [x.strip() for x in plain.splitlines() if x.strip()]
        defn = " ".join(lines)[:2600]
        if not defn and not examples:
            continue
        if not title:
            try:
                title = index[len(senses)].split(" ", 1)[-1].strip("【】 ")
            except Exception:
                title = ""
        senses.append({
            "no": str(len(senses) + 1),
            "title": title,
            "gram": gram,
            "def": defn,
            "examples": examples[:8],
        })

    if not senses:
        return None
    return {
        "v": 2,
        "kind": "longman",
        "head": word,
        "phon": phon,
        "pos": pos,
        "index": index,
        "etym": etym,
        "senses": senses,
    }


def parse_collocations(xmls, word: str) -> dict | None:
    raw = "".join(xmls or [])
    paras = re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S)
    if not paras:
        return None
    head = _clean(paras[0])
    pos = ""
    m = re.search(r"\b(verb|noun|adjective|adverb)\b", head)
    if m:
        pos = m.group(1)
    senses = []
    current = None
    for para in paras[1:]:
        sup = _first(r"<sup[^>]*>\s*(\d+)\s*</sup>", para)
        span = _first(r"<span[^>]*>(.*?)</span>", para)
        if sup:
            current = {"no": sup, "title": span, "groups": []}
            senses.append(current)
            continue
        if current is None:
            current = {"no": "", "title": "", "groups": []}
            senses.append(current)
        label = _first(r"<u[^>]*>(.*?)</u>", para).strip()
        bs = [_clean(x) for x in re.findall(r"<b[^>]*>(.*?)</b>", para, re.S)]
        its = [_clean(x) for x in re.findall(r"<i[^>]*>(.*?)</i>", para, re.S)]
        items = []
        for b in bs:
            if not b:
                continue
            for part in re.split(r"\s*\|\s*", b):
                part = part.strip()
                if part:
                    items.append({"text": part, "example": ""})
        for i, ex in enumerate([x for x in its if x]):
            if items and i < len(items) and not items[i]["example"]:
                items[i]["example"] = ex
            elif items:
                items[-1]["example"] = items[-1].get("example") or ex
        if items:
            current["groups"].append({"label": label, "items": items})
    senses = [s for s in senses if s["groups"]]
    if not senses:
        return None
    return {
        "v": 2,
        "kind": "collocations",
        "head": word,
        "phon": "",
        "pos": pos,
        "index": [s["title"] for s in senses if s["title"]],
        "etym": "",
        "senses": senses,
    }
