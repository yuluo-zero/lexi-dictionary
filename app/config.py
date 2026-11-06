# -*- coding: utf-8 -*-
"""Paths, settings and small shared helpers."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading

APP_NAME = "划词词典"
APP_EN = "Lexi"
VERSION = "1.1.0"

_lock = threading.RLock()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> str:
    """Folder that holds the exe (portable install root)."""
    env = os.environ.get("LEXI_HOME")
    if env:
        return os.path.abspath(env)
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = app_root()
DATA_DIR = os.path.join(ROOT, "data")
DICT_DIR = os.path.join(DATA_DIR, "dict")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
TTS_CACHE = os.path.join(CACHE_DIR, "tts")
LOG_DIR = os.path.join(DATA_DIR, "logs")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
USER_DB = os.path.join(DATA_DIR, "user.db")


def ensure_dirs():
    for d in (DATA_DIR, DICT_DIR, CACHE_DIR, TTS_CACHE, LOG_DIR):
        os.makedirs(d, exist_ok=True)


def resource_path(*parts) -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


DEFAULTS = {
    # appearance
    "theme": "system",              # system | light | dark
    "font_scale": 1.0,
    "language": "zh",
    # floating ball
    "ball_enabled": True,
    "ball_pos": None,               # [x, y] top-left (expanded position)
    "ball_docked": False,
    "ball_side": "right",
    "ball_y": None,
    "ball_opacity": 1.0,
    # selection lookup
    "selection_enabled": True,
    "selection_delay_ms": 90,
    "restore_clipboard": True,
    "selection_in_terminals": False,
    "bubble_timeout_s": 8,
    "bubble_source": "auto",         # auto / local / ecdict / wordnet / youdao
    "bubble_online_fallback": False,
    "bubble_expand_sources": ["local", "ecdict", "wordnet"],
    "bubble_enabled": True,
    # dictionaries
    "cn_en": True,                  # 中英互译
    "en_en": True,                  # 英英互译
    "online_dict": True,
    "offline_first": True,
    "online_first": True,           # 有网时优先用在线释义
    "full_content": False,          # 完整模式：不截断释义/例句
    "parallel_sources": False,      # 「全部」并列显示所有来源
    "source_order": ["ecdict", "wordnet", "local", "collins", "youdao", "merriam"],
    "fulltext_enabled": False,      # 全文搜索（默认关闭）
    "mw_collegiate_key": "",
    "mw_learners_key": "",
    "mw_variant": "collegiate",     # collegiate / learners
    "merge_restore_enabled": False, # 恢复备份时允许合并
    "source_ecdict": True,          # 英汉 ECDICT
    "source_cedict": True,          # 中英 CC-CEDICT
    "source_wordnet": True,         # 英英 WordNet
    "source_youdao": True,          # 在线释义/例句
    "source_datamuse": True,        # 在线同义词
    "target_exam": "",              # zk/gk/cet4/cet6/ky/toefl/ielts/gre
    # translation
    "translate_provider": "mymemory",   # mymemory | google | deepl
    "translate_key": "",
    "deepl_endpoint": "https://api-free.deepl.com/v2/translate",
    # pronunciation
    "tts_online": True,
    "tts_system": True,
    "tts_accent": "us",             # us | uk
    # system
    "autostart": False,
    "close_to_tray": True,
    "history_enabled": True,
    "max_history": 800,
    "first_run": True,
    "window_geometry": None,
}


def load_settings() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k, v in saved.items():
                if k in DEFAULTS:
                    data[k] = v
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return data


def save_settings(settings: dict):
    ensure_dirs()
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def exe_path() -> str:
    return os.path.abspath(sys.executable) if is_frozen() else ""


def startup_command() -> str:
    if is_frozen():
        return '"%s" --autostart' % os.path.abspath(sys.executable)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    runner = pyw if os.path.exists(pyw) else sys.executable
    main = os.path.join(app_root(), "main.py")
    return '"%s" "%s" --autostart' % (runner, main)
