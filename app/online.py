# -*- coding: utf-8 -*-
"""Online dictionaries, translation providers and pronunciation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config
from .lexicon import has_cjk

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str, ttl: float = 3600):
    with _cache_lock:
        item = _cache.get(key)
        if item and time.time() - item[0] < ttl:
            return item[1]
    return None


def _cache_put(key: str, value):
    with _cache_lock:
        if len(_cache) > 400:
            _cache.clear()
        _cache[key] = (time.time(), value)


def http_json(url: str, timeout: float = 4.0, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", "replace"))


def http_post_json(url: str, data: bytes, timeout: float = 6.0, headers: dict | None = None):
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", "replace"))


# --------------------------------------------------------------------------- Youdao
def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _tr_text(tr) -> str:
    """Pull plain text out of Youdao's tr structures."""
    if isinstance(tr, str):
        return tr
    if isinstance(tr, dict):
        for key in ("tr", "l", "i"):
            if key in tr:
                return _tr_text(tr[key])
        return ""
    if isinstance(tr, list):
        return " ".join(t for t in (_tr_text(x) for x in tr) if t).strip()
    return ""


def youdao_lookup(word: str, full: bool = False):
    key = "youdao:" + word.lower() + (":full" if full else "")
    hit = _cache_get(key, 86400)
    if hit is not None:
        return hit
    url = "https://dict.youdao.com/jsonapi?" + urllib.parse.urlencode({"q": word})
    try:
        data = http_json(url, timeout=5.0)
    except Exception:
        return None
    out = {"phonetic_us": "", "phonetic_uk": "", "cn": [], "en": [], "examples": [], "web": [], "phrs": [], "exam_sents": [], "collins": []}
    ec = data.get("ec") or {}
    for w in _as_list(ec.get("word"))[:1]:
        out["phonetic_us"] = w.get("usphone") or ""
        out["phonetic_uk"] = w.get("ukphone") or ""
        for tr in _as_list(w.get("trs")):
            txt = _tr_text(tr.get("tr") if isinstance(tr, dict) else tr)
            if txt:
                out["cn"].append(txt)
    ee = data.get("ee") or {}
    for w in _as_list(ee.get("word"))[:1]:
        for trs in _as_list(w.get("trs")):
            pos = trs.get("pos") or ""
            defs = []
            for tr in _as_list(trs.get("tr")):
                txt = _tr_text(tr.get("l") if isinstance(tr, dict) else tr)
                if txt:
                    defs.append(txt)
            if defs:
                out["en"].append({"pos": pos, "defs": defs})
    for pair in _as_list((data.get("blng_sents_part") or {}).get("sentence-pair"))[:20 if full else 6]:
        en = pair.get("sentence") or ""
        zh = pair.get("sentence-translation") or ""
        if en:
            out["examples"].append({"en": en, "zh": zh})
    for item in _as_list((data.get("web_trans") or {}).get("web-translation"))[:1]:
        for tr in _as_list(item.get("trans"))[:20 if full else 6]:
            val = tr.get("value") or ""
            if val:
                out["web"].append(val)
    for entry in _as_list((data.get("phrs") or {}).get("phrs"))[:30 if full else 10]:
        phr = entry.get("phr") or {}
        head = _tr_text((phr.get("headword") or {}).get("l") or {})
        zh = ""
        for tr in _as_list(phr.get("trs")):
            zh = _tr_text(tr.get("tr") if isinstance(tr, dict) else tr)
            if zh:
                break
        if head and head.lower() != word.lower():
            out["phrs"].append({"en": head, "zh": zh})
    collins = data.get("collins") or {}
    for ce in _as_list(collins.get("collins_entries")):
        for ent in _as_list((ce.get("entries") or {}).get("entry")):
            for te in _as_list(ent.get("tran_entry")):
                pe = te.get("pos_entry") or {}
                tran = re.sub(r"<[^>]+>", "", te.get("tran") or pe.get("tran") or "").strip()
                examples = []
                for sent in _as_list((te.get("exam_sents") or {}).get("sent")):
                    en = sent.get("eng_sent") or ""
                    zh = sent.get("chn_sent") or ""
                    if en:
                        examples.append({"en": en, "zh": zh})
                if tran:
                    out["collins"].append(
                        {"pos": pe.get("pos_tips") or pe.get("pos", ""), "def": tran,
                         "examples": examples[:5 if full else 2]}
                    )
                for sent in _as_list((te.get("exam_sents") or {}).get("sent")):
                    en = sent.get("eng_sent") or ""
                    zh = sent.get("chn_sent") or ""
                    if en:
                        out["exam_sents"].append({"en": en, "zh": zh, "pos": pe.get("pos", "")})
    out["exam_sents"] = out["exam_sents"][:20 if full else 6]
    out["collins"] = out["collins"][:20 if full else 6]
    if not (out["cn"] or out["en"] or out["examples"] or out["phrs"] or out["exam_sents"] or out["collins"]):
        return None
    _cache_put(key, out)
    return out


# --------------------------------------------------------------------------- Merriam-Webster
def merriam_lookup(word: str, key: str, variant: str = "collegiate"):
    """Official Merriam-Webster learner/collegiate JSON API (key required)."""
    key = (key or "").strip()
    if not key:
        return None
    kind = "learners" if variant == "learners" else "collegiate"
    url = (
        "https://www.dictionaryapi.com/api/v3/references/"
        + kind
        + "/json/"
        + urllib.parse.quote(word)
        + "?key="
        + urllib.parse.quote(key)
    )
    try:
        data = http_json(url, timeout=6.0)
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    suggestions = [x for x in data if isinstance(x, str)][:8]
    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        hwi = item.get("hwi") or {}
        hw = (hwi.get("hw") or "").replace("*", "").strip()
        pos = (item.get("fl") or "").strip()
        defs = [re.sub(r"\{[^}]+\}", "", d).strip() for d in (item.get("shortdef") or [])]
        defs = [d for d in defs if d]
        phonetic = ""
        for pr in (hwi.get("prs") or []):
            if pr.get("mw"):
                phonetic = pr["mw"]
                break
        if hw and defs:
            entries.append({"word": hw, "pos": pos, "defs": defs[:4], "phonetic": phonetic})
        if len(entries) >= 10:
            break
    if not entries and not suggestions:
        return None
    return {"variant": kind, "entries": entries, "suggestions": suggestions}


# --------------------------------------------------------------------------- Free Dictionary
def dictionary_api(word: str):
    key = "dict:" + word.lower()
    hit = _cache_get(key, 86400)
    if hit is not None:
        return hit
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    try:
        data = http_json(url, timeout=4.0)
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    out = {"phonetics": [], "meanings": [], "origin": ""}
    for item in data[:3]:
        out["origin"] = out["origin"] or (item.get("origin") or "")
        for ph in item.get("phonetics") or []:
            txt = ph.get("text") or ""
            audio = ph.get("audio") or ""
            if txt or audio:
                out["phonetics"].append({"text": txt, "audio": audio})
        for m in item.get("meanings") or []:
            pos = m.get("partOfSpeech") or ""
            defs = []
            for d in m.get("definitions") or []:
                defs.append(
                    {
                        "definition": d.get("definition") or "",
                        "example": d.get("example") or "",
                        "synonyms": (d.get("synonyms") or [])[:6],
                    }
                )
            if defs:
                out["meanings"].append({"pos": pos, "definitions": defs})
    _cache_put(key, out)
    return out


def datamuse_synonyms(word: str):
    key = "syn:" + word.lower()
    hit = _cache_get(key, 86400)
    if hit is not None:
        return hit
    url = "https://api.datamuse.com/words?" + urllib.parse.urlencode({"rel_syn": word, "max": 10})
    try:
        data = http_json(url, timeout=3.5)
        words = [d["word"] for d in data if isinstance(d, dict) and d.get("word")]
    except Exception:
        words = []
    _cache_put(key, words)
    return words


# --------------------------------------------------------------------------- translation
def _split_text(text: str, limit: int = 450):
    if len(text) <= limit:
        return [text]
    chunks = []
    buf = ""
    for piece in re.split(r"(?<=[。！？!?；;\.\n])", text):
        if len(buf) + len(piece) > limit and buf:
            chunks.append(buf)
            buf = ""
        buf += piece
    if buf:
        chunks.append(buf)
    return chunks


def _mymemory(text: str, src: str, tgt: str):
    parts = []
    for chunk in _split_text(text):
        url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
            {"q": chunk, "langpair": f"{src}|{tgt}"}
        )
        data = http_json(url, timeout=6.0)
        translated = (data.get("responseData") or {}).get("translatedText") or ""
        if not translated or "MYMEMORY WARNING" in translated.upper():
            raise RuntimeError("MyMemory 额度已用尽，请稍后再试或切换翻译服务")
        parts.append(translated)
    return " ".join(parts).strip()


def _google(text: str, src: str, tgt: str):
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text}
    )
    data = http_json(url, timeout=5.0)
    return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()


def _deepl(text: str, src: str, tgt: str, key: str, endpoint: str):
    payload = json.dumps({"text": [text], "source_lang": src.upper(), "target_lang": tgt.upper()}).encode()
    data = http_post_json(endpoint, payload, headers={"Authorization": f"DeepL-Auth-Key {key}"})
    return data["translations"][0]["text"].strip()


def translate(text: str, settings: dict):
    """Translate a sentence between Chinese and English."""
    text = text.strip()
    if not text:
        return None
    src = "zh" if has_cjk(text) else "en"
    if has_cjk(text) and not re.search(r"[\u4e00-\u9fff]", text):
        src = "en"
    tgt = "en" if src == "zh" else "zh"
    provider = settings.get("translate_provider", "mymemory")
    key = (settings.get("translate_key") or "").strip()
    result = {"source": text, "text": "", "src": src, "tgt": tgt, "provider": provider, "error": ""}
    try:
        if provider == "deepl":
            if not key:
                raise RuntimeError("请先在设置中填入 DeepL API Key")
            result["text"] = _deepl(text, src, tgt, key, settings.get("deepl_endpoint") or "https://api-free.deepl.com/v2/translate")
        elif provider == "google":
            result["text"] = _google(text, src, tgt)
        else:
            result["text"] = _mymemory(text, "zh-CN" if src == "zh" else "en", "en" if src == "zh" else "zh-CN")
    except Exception as exc:
        result["error"] = str(exc) or "网络不可用"
    return result


def provider_name(code: str) -> str:
    return {"mymemory": "MyMemory 免费", "google": "Google 免费", "deepl": "DeepL"}.get(code, code)


# --------------------------------------------------------------------------- pronunciation
def tts_cache_path(word: str, accent: str) -> str:
    digest = hashlib.md5((word + "|" + accent).encode("utf-8")).hexdigest()[:16]
    return os.path.join(config.TTS_CACHE, f"{digest}.mp3")


def fetch_tts(word: str, accent: str = "us") -> str | None:
    """Download Youdao's dict voice into the local cache; return mp3 path."""
    path = tts_cache_path(word, accent)
    if os.path.exists(path) and os.path.getsize(path) > 800:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    typ = "1" if accent == "uk" else "2"
    if has_cjk(word):
        url = "https://dict.youdao.com/dictvoice?" + urllib.parse.urlencode({"audio": word, "le": "zh"})
    else:
        url = "https://dict.youdao.com/dictvoice?" + urllib.parse.urlencode({"audio": word, "type": typ})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        if len(data) < 800:
            return None
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        return None


def clear_tts_cache():
    n = 0
    for root, _dirs, files in os.walk(config.TTS_CACHE):
        for name in files:
            try:
                os.remove(os.path.join(root, name))
                n += 1
            except OSError:
                pass
    return n
