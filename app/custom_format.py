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


def soft_case(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        text = text.lower()
        text = text[:1].upper() + text[1:]
    return text


def category_label(text: str) -> str:
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
    return soft_case(text)


def parse_thesaurus(xmls, word: str) -> dict | None:
    raw = "".join(xmls or [])
    pos = ""
    pm = re.search(
        r'<font[^>]*color="#209020"[^>]*>\s*([^<]+?)\s*</font>', raw, re.I
    )
    if pm:
        pos = pm.group(1).strip()
    marks = list(re.finditer(r"<b>\s*(\d+)\s*</b>", raw))
    senses = []
    for idx, mark in enumerate(marks):
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(raw)
        block = raw[mark.end():end]
        examples = [_clean(x) for x in re.findall(
            r'<font[^>]*color="#808080"[^>]*>(.*?)</font>', block, re.S
        )]
        plain = _clean(block)
        plain = _remove_all(plain, examples)
        plain = re.sub(r"<[^>]+>", " ", plain)
        defn = " ".join(x.strip() for x in plain.splitlines() if x.strip())
        defn = defn.strip(" :;")
        if not defn and not examples:
            continue
        senses.append({
            "no": mark.group(1),
            "title": "",
            "gram": "",
            "def": defn[:2600],
            "examples": [x for x in examples if x][:8],
        })
    if not senses:
        examples = [_clean(x) for x in re.findall(
            r'<font[^>]*color="#808080"[^>]*>(.*?)</font>', raw, re.S
        )]
        examples = [x for x in examples if x]
        plain = _clean(raw)
        plain = _remove_all(plain, examples)
        lines = [x.strip() for x in plain.splitlines() if x.strip()]
        defn = " ".join(lines)[:2600]
        if defn or examples:
            senses.append({
                "no": "1",
                "title": "",
                "gram": "",
                "def": defn,
                "examples": examples[:8],
            })

    if not senses:
        return None
    return {
        "v": 2,
        "kind": "thesaurus",
        "head": word,
        "phon": "",
        "pos": pos,
        "index": [],
        "etym": "",
        "senses": senses,
    }


def encode(data: dict) -> str:
    return PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def preview_text(data: dict, max_senses: int = 1) -> str:
    senses = (data or {}).get("senses") or []
    out = []
    for sense in senses[:max_senses]:
        title = soft_case(sense.get("title", ""))
        defn = (sense.get("def") or "").strip()
        line = defn
        if title:
            line = (title + " — " + defn).strip(" —")
        if line:
            out.append(line)
    return "\n".join(out)


def to_html(data: dict, expanded: bool = True) -> str:
    esc = html.escape
    kind = (data or {}).get("kind")
    senses = (data or {}).get("senses") or []
    limit = len(senses) if expanded else min(3, len(senses))
    parts = ['<div style="line-height:1.5">']
    for sense in senses[:limit]:
        title = soft_case(sense.get("title", ""))
        no = (sense.get("no") or "").strip()
        head = " ".join(x for x in (no, title) if x)
        if head:
            parts.append('<p style="margin:6px 0 2px 0"><b>%s</b>' % esc(head))
            gram = (sense.get("gram") or "").strip()
            if gram:
                parts.append(' <span style="color:#888">%s</span>' % esc(gram))
            parts.append("</p>")
        if kind == "collocations":
            for group in sense.get("groups") or []:
                label = category_label(group.get("label", ""))
                if label:
                    parts.append('<p style="margin:4px 0 1px 0;color:#777">%s</p>' % esc(label))
                for item in group.get("items") or []:
                    parts.append('<p style="margin:1px 0">• %s' % esc(item.get("text", "")))
                    if expanded and item.get("example"):
                        parts.append('<br><span style="color:#888">%s</span>' % esc(item["example"]))
                    parts.append("</p>")
        else:
            defn = (sense.get("def") or "").strip()
            if defn:
                parts.append('<p style="margin:2px 0">%s</p>' % esc(defn))
            if expanded:
                for ex in sense.get("examples") or []:
                    parts.append('<p style="margin:1px 0;color:#888">• %s</p>' % esc(ex))
    if expanded and (data or {}).get("etym"):
        parts.append('<p style="margin:8px 0 1px 0;color:#777">词源</p>')
        parts.append('<p style="margin:1px 0;color:#888">%s</p>' % esc(data["etym"]))
    parts.append("</div>")
    return "".join(parts)


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
        examples = [_clean(x) for x in re.findall(
            r'<font[^>]*color="#004080"[^>]*>(.*?)</font>', body, re.S
        )]
        examples = [x for x in examples if x]
        plain = _clean(body)
        plain = _remove_all(plain, examples + [etym])
        lines = [
            line.strip() for line in plain.splitlines()
            if line.strip() and not re.match(r"^\d+【", line.strip())
        ]
        defn = " ".join(lines)[:2600]
        if defn or examples:
            senses.append({
                "no": "1",
                "title": "",
                "gram": "",
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
