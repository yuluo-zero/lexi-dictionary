# -*- coding: utf-8 -*-
"""User data: history, wordbook and settings helpers."""
from __future__ import annotations

import copy
import csv
import datetime
import json
import os
import sqlite3
import threading
import time
import zlib

from fsrs import Card, Rating, Scheduler, State

from . import config


class Store:
    def __init__(self, path: str = config.USER_DB):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.RLock()
        self.con = sqlite3.connect(path, check_same_thread=False, timeout=8)
        self.con.row_factory = sqlite3.Row
        self._scheduler = Scheduler(
            desired_retention=0.9,
            learning_steps=[datetime.timedelta(minutes=1), datetime.timedelta(minutes=10)],
            relearning_steps=[datetime.timedelta(minutes=10)],
        )
        self._init()

    def _init(self):
        with self._lock:
            self.con.executescript(
                """
                CREATE TABLE IF NOT EXISTS history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    kind TEXT,
                    brief TEXT,
                    ts INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts DESC);
                CREATE TABLE IF NOT EXISTS wordbook(
                    word TEXT PRIMARY KEY,
                    phonetic TEXT,
                    brief TEXT,
                    note TEXT,
                    ts INTEGER NOT NULL
                );
                """
            )
            # Lightweight migration for the review scheduler.
            cols = {r[1] for r in self.con.execute("PRAGMA table_info(wordbook)").fetchall()}
            if "stability" not in cols:
                # Keep a consistent copy before the FSRS schema migration.
                try:
                    backup = sqlite3.connect(self.path + ".bak")
                    self.con.backup(backup)
                    backup.close()
                except Exception:
                    pass
            for name, decl in (
                ("due", "INTEGER NOT NULL DEFAULT 0"),
                ("interval", "INTEGER NOT NULL DEFAULT 0"),
                ("ease", "REAL NOT NULL DEFAULT 2.5"),
                ("reps", "INTEGER NOT NULL DEFAULT 0"),
                ("lapses", "INTEGER NOT NULL DEFAULT 0"),
                ("last_review", "INTEGER NOT NULL DEFAULT 0"),
                ("stability", "REAL NOT NULL DEFAULT 0"),
                ("difficulty", "REAL NOT NULL DEFAULT 0"),
                ("fsrs_state", "INTEGER NOT NULL DEFAULT 0"),
                ("fsrs_step", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in cols:
                    self.con.execute("ALTER TABLE wordbook ADD COLUMN %s %s" % (name, decl))
            self.con.commit()

    # ------------------------------------------------------------------ history
    def add_history(self, text: str, kind: str, brief: str = ""):
        text = text.strip()
        if not text:
            return
        now = int(time.time())
        with self._lock:
            last = self.con.execute("SELECT id,text,ts FROM history ORDER BY id DESC LIMIT 1").fetchone()
            if last and last["text"] == text and now - last["ts"] < 600:
                self.con.execute("UPDATE history SET ts=? WHERE id=?", (now, last["id"]))
            else:
                self.con.execute(
                    "INSERT INTO history(text,kind,brief,ts) VALUES(?,?,?,?)", (text, kind, brief, now)
                )
            keep = int(config.load_settings().get("max_history", 800) or 800)
            self.con.execute(
                "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            self.con.commit()

    def history(self, limit: int = 500):
        with self._lock:
            rows = self.con.execute(
                "SELECT id,text,kind,brief,ts FROM history ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_history_ids(self, ids):
        ids = [int(i) for i in ids]
        if not ids:
            return
        with self._lock:
            marks = ",".join("?" for _ in ids)
            self.con.execute("DELETE FROM history WHERE id IN (%s)" % marks, ids)
            self.con.commit()

    def clear_history(self):
        with self._lock:
            self.con.execute("DELETE FROM history")
            self.con.commit()

    # ------------------------------------------------------------------ wordbook
    def add_word(self, word: str, phonetic: str = "", brief: str = ""):
        with self._lock:
            self.con.execute(
                "INSERT INTO wordbook(word,phonetic,brief,ts) VALUES(?,?,?,?) "
                "ON CONFLICT(word) DO UPDATE SET phonetic=excluded.phonetic, brief=excluded.brief",
                (word.strip(), phonetic, brief, int(time.time())),
            )
            self.con.commit()

    def remove_word(self, word: str):
        with self._lock:
            self.con.execute("DELETE FROM wordbook WHERE word=?", (word,))
            self.con.commit()

    def has_word(self, word: str) -> bool:
        with self._lock:
            return (
                self.con.execute("SELECT 1 FROM wordbook WHERE word=?", (word,)).fetchone()
                is not None
            )

    def words(self, query: str = ""):
        with self._lock:
            if query:
                rows = self.con.execute(
                    "SELECT * FROM wordbook WHERE word LIKE ? ORDER BY ts DESC",
                    ("%" + query + "%",),
                ).fetchall()
            else:
                rows = self.con.execute(
                    "SELECT * FROM wordbook ORDER BY ts DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def due_count(self) -> int:
        now = int(time.time())
        with self._lock:
            return self.con.execute(
                "SELECT count(1) FROM wordbook WHERE due<=?", (now,)
            ).fetchone()[0]

    def due_words(self, limit: int = 50):
        now = int(time.time())
        with self._lock:
            rows = self.con.execute(
                "SELECT * FROM wordbook WHERE due<=? ORDER BY due, ts LIMIT ?",
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _card_from_row(self, row) -> Card:
        word = row["word"]
        due_ts = int(row["due"] or 0)
        due = datetime.datetime.fromtimestamp(due_ts or time.time(), tz=datetime.timezone.utc)
        last = int(row["last_review"] or 0)
        last_dt = datetime.datetime.fromtimestamp(last, tz=datetime.timezone.utc) if last else None
        state = int(row["fsrs_state"] or 0)
        reps = int(row["reps"] or 0)
        interval = int(row["interval"] or 0)
        if state <= 0 and reps > 0 and interval > 0:
            state = int(State.Review)
            stability = max(1.0, float(interval))
            difficulty = 5.0
        else:
            stability = float(row["stability"] or 0) or None
            difficulty = float(row["difficulty"] or 0) or None
        return Card(
            card_id=zlib.crc32(word.encode("utf-8")) & 0x7FFFFFFF,
            state=State(state) if state in (1, 2, 3) else State.Learning,
            step=int(row["fsrs_step"] or 0),
            stability=stability,
            difficulty=difficulty,
            due=due,
            last_review=last_dt,
        )

    def review_word(self, word: str, rating: int) -> int:
        """FSRS review. rating: 1 Again, 2 Hard, 3 Good, 4 Easy."""
        rating = max(1, min(4, int(rating)))
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now = int(now_dt.timestamp())
        with self._lock:
            row = self.con.execute("SELECT * FROM wordbook WHERE word=?", (word,)).fetchone()
            if not row:
                return now
            card = self._card_from_row(row)
            next_card, _ = self._scheduler.review_card(card, Rating(rating), review_datetime=now_dt)
            due = int(next_card.due.timestamp())
            stability = float(next_card.stability or 0)
            difficulty = float(next_card.difficulty or 0)
            state = int(next_card.state)
            step = int(next_card.step or 0)
            reps = int(row["reps"] or 0) + 1
            lapses = int(row["lapses"] or 0) + (1 if rating == 1 else 0)
            interval = max(0, int((due - now) // 86400))
            self.con.execute(
                "UPDATE wordbook SET due=?,interval=?,ease=?,reps=?,lapses=?,last_review=?,"
                "stability=?,difficulty=?,fsrs_state=?,fsrs_step=? WHERE word=?",
                (due, interval, 11.0 - difficulty, reps, lapses, now,
                 stability, difficulty, state, step, word),
            )
            self.con.commit()
        return due

    def preview_word(self, word: str) -> dict:
        """Seconds until next review for Again/Hard/Good/Easy, for button labels."""
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        with self._lock:
            row = self.con.execute("SELECT * FROM wordbook WHERE word=?", (word,)).fetchone()
        if not row:
            return {}
        card = self._card_from_row(row)
        out = {}
        for rating in (1, 2, 3, 4):
            next_card, _ = self._scheduler.review_card(
                copy.deepcopy(card), Rating(rating), review_datetime=now_dt
            )
            out[rating] = max(0, int((next_card.due - now_dt).total_seconds()))
        return out

    def is_mastered(self, word: str) -> bool:
        with self._lock:
            row = self.con.execute(
                "SELECT stability,fsrs_state FROM wordbook WHERE word=?", (word,)
            ).fetchone()
        return bool(row and int(row["fsrs_state"] or 0) == 2 and float(row["stability"] or 0) >= 21)


    # ------------------------------------------------------------------ backup
    BACKUP_APP = "lexi-dictionary"
    BACKUP_VERSION = 1

    def export_backup(self, path: str) -> dict:
        with self._lock:
            words = [dict(r) for r in self.con.execute("SELECT * FROM wordbook ORDER BY ts").fetchall()]
            history = [
                {"text": r["text"], "kind": r["kind"], "brief": r["brief"], "ts": r["ts"]}
                for r in self.con.execute("SELECT text,kind,brief,ts FROM history ORDER BY ts").fetchall()
            ]
        payload = {
            "app": self.BACKUP_APP,
            "version": self.BACKUP_VERSION,
            "exported": int(time.time()),
            "wordbook": words,
            "history": history,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        return {"words": len(words), "history": len(history)}

    @staticmethod
    def _validate_backup(data) -> str:
        if not isinstance(data, dict):
            return "备份不是 JSON 对象"
        if data.get("app") != Store.BACKUP_APP:
            return "不是划词词典的备份"
        if data.get("version") != Store.BACKUP_VERSION:
            return "备份版本不支持"
        words = data.get("wordbook")
        history = data.get("history", [])
        if not isinstance(words, list) or not isinstance(history, list):
            return "备份结构不完整"
        if len(words) > 100000 or len(history) > 100000:
            return "备份条目过多"
        for w in words:
            if not isinstance(w, dict) or not isinstance(w.get("word"), str) or not w["word"].strip():
                return "存在无效生词"
            if len(w["word"]) > 200:
                return "存在过长生词"
            for key in ("due", "reps", "lapses", "last_review", "fsrs_state", "fsrs_step"):
                if key in w and not isinstance(w[key], int):
                    return "生词字段类型错误"
            for key in ("stability", "difficulty"):
                if key in w and not isinstance(w[key], (int, float)):
                    return "生词字段类型错误"
            if int(w.get("fsrs_state", 0)) not in (0, 1, 2, 3):
                return "复习状态无效"
        for h in history:
            if not isinstance(h, dict) or not isinstance(h.get("text"), str) or not h["text"].strip():
                return "存在无效历史记录"
            if not isinstance(h.get("ts", 0), int):
                return "历史时间无效"
        return ""

    def inspect_backup(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        error = self._validate_backup(data)
        if error:
            raise ValueError(error)
        words = {w["word"].strip().lower() for w in data["wordbook"]}
        with self._lock:
            current = {
                r["word"].strip().lower() for r in self.con.execute("SELECT word FROM wordbook").fetchall()
            }
        return {
            "words": len(words),
            "history": len(data.get("history", [])),
            "overlap": len(words & current),
            "new_words": len(words - current),
        }

    def import_backup(self, path: str, mode: str = "replace") -> dict:
        mode = "merge" if mode == "merge" else "replace"
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        error = self._validate_backup(data)
        if error:
            raise ValueError(error)
        # Keep a consistent copy of the current DB before touching it.
        try:
            backup = sqlite3.connect(self.path + ".pre-restore.bak")
            self.con.backup(backup)
            backup.close()
        except Exception:
            pass
        words = data["wordbook"]
        history = data.get("history", [])
        with self._lock:
            existing_words = {
                r["word"] for r in self.con.execute("SELECT word FROM wordbook").fetchall()
            }
            existing_history = {
                (r["text"], int(r["ts"])) for r in self.con.execute("SELECT text,ts FROM history").fetchall()
            }
            added_words = 0
            added_history = 0
            try:
                self.con.execute("BEGIN")
                if mode == "replace":
                    self.con.execute("DELETE FROM wordbook")
                    self.con.execute("DELETE FROM history")
                    existing_words.clear()
                    existing_history.clear()
                for w in words:
                    word = w["word"].strip()
                    if mode == "merge" and word in existing_words:
                        continue
                    self.con.execute(
                        "INSERT OR REPLACE INTO wordbook("
                        "word,phonetic,brief,note,ts,due,interval,ease,reps,lapses,last_review,"
                        "stability,difficulty,fsrs_state,fsrs_step"
                        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            word,
                            w.get("phonetic", ""),
                            w.get("brief", ""),
                            w.get("note", ""),
                            int(w.get("ts", time.time())),
                            int(w.get("due", 0)),
                            int(w.get("interval", 0)),
                            float(w.get("ease", 2.5)),
                            int(w.get("reps", 0)),
                            int(w.get("lapses", 0)),
                            int(w.get("last_review", 0)),
                            float(w.get("stability", 0)),
                            float(w.get("difficulty", 0)),
                            int(w.get("fsrs_state", 0)),
                            int(w.get("fsrs_step", 0)),
                        ),
                    )
                    existing_words.add(word)
                    added_words += 1
                for h in history:
                    text = h["text"].strip()
                    ts = int(h.get("ts", time.time()))
                    key = (text, ts)
                    if mode == "merge" and key in existing_history:
                        continue
                    self.con.execute(
                        "INSERT INTO history(text,kind,brief,ts) VALUES(?,?,?,?)",
                        (text, h.get("kind", ""), h.get("brief", ""), ts),
                    )
                    existing_history.add(key)
                    added_history += 1
                self.con.commit()
            except Exception:
                self.con.rollback()
                raise
        return {
            "mode": mode,
            "words": len(words),
            "history": len(history),
            "added_words": added_words,
            "added_history": added_history,
        }

    def export_words(self, path: str):
        rows = self.words()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["单词", "音标", "释义", "加入时间"])
            for r in rows:
                w.writerow([r["word"], r["phonetic"], r["brief"], time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"]))])
        return len(rows)
