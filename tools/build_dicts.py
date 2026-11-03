# -*- coding: utf-8 -*-
"""Build the offline dictionary databases used by the app.

Inputs (downloads/):
  ecdict.csv          ECDICT full CSV (770k entries, EN -> ZH)
  cedict.txt.gz       CC-CEDICT (ZH <-> EN)
  wordnet.zip         NLTK WordNet corpus (EN -> EN)

Outputs: <out>/ecdict.db, cedict.db, wordnet.db
"""
from __future__ import annotations

import csv
import gzip
import io
import os
import re
import sqlite3
import sys
import time
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = os.path.join(BASE, "downloads")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "build", "dict")


def log(*a):
    print(*a, flush=True)


def fresh(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA cache_size=-200000")
    return con


# --------------------------------------------------------------------------- ECDICT
def build_ecdict():
    src = os.path.join(DL, "ecdict.csv")
    dst = os.path.join(OUT, "ecdict.db")
    log("[ecdict] building", dst)
    csv.field_size_limit(10 ** 9)
    con = fresh(dst)
    con.executescript(
        """
        CREATE TABLE words(
            id INTEGER PRIMARY KEY,
            word TEXT NOT NULL,
            lword TEXT NOT NULL,
            phonetic TEXT,
            definition TEXT,
            translation TEXT,
            pos TEXT,
            collins INTEGER DEFAULT 0,
            oxford INTEGER DEFAULT 0,
            tag TEXT,
            bnc INTEGER DEFAULT 0,
            frq INTEGER DEFAULT 0,
            exchange TEXT,
            audio TEXT
        );
        CREATE TABLE forms(form TEXT NOT NULL, base TEXT NOT NULL);
        """
    )
    rows = []
    forms = []
    n = 0
    t0 = time.time()
    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            word = (r.get("word") or "").strip()
            if not word:
                continue
            lword = word.lower()
            try:
                collins = int(float(r.get("collins") or 0))
            except ValueError:
                collins = 0
            try:
                oxford = int(float(r.get("oxford") or 0))
            except ValueError:
                oxford = 0
            try:
                bnc = int(float(r.get("bnc") or 0))
            except ValueError:
                bnc = 0
            try:
                frq = int(float(r.get("frq") or 0))
            except ValueError:
                frq = 0
            rows.append(
                (
                    word,
                    lword,
                    (r.get("phonetic") or "").strip(),
                    (r.get("definition") or "").strip(),
                    (r.get("translation") or "").strip(),
                    (r.get("pos") or "").strip(),
                    collins,
                    oxford,
                    (r.get("tag") or "").strip(),
                    bnc,
                    frq,
                    (r.get("exchange") or "").strip(),
                    (r.get("audio") or "").strip(),
                )
            )
            ex = (r.get("exchange") or "").strip()
            if ex:
                for part in ex.split("/"):
                    if ":" not in part:
                        continue
                    _, vals = part.split(":", 1)
                    for v in vals.split(","):
                        v = v.strip().lower()
                        if v and v != lword:
                            forms.append((v, word))
            n += 1
            if n % 100000 == 0:
                con.executemany(
                    "INSERT INTO words(word,lword,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,audio)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                rows.clear()
                forms and con.executemany("INSERT INTO forms(form,base) VALUES(?,?)", forms)
                forms.clear()
                log("  ", n, "rows", round(time.time() - t0, 1), "s")
    if rows:
        con.executemany(
            "INSERT INTO words(word,lword,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,audio)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    if forms:
        con.executemany("INSERT INTO forms(form,base) VALUES(?,?)", forms)
    con.execute("CREATE INDEX idx_words_lword ON words(lword)")
    con.execute("CREATE INDEX idx_words_frq ON words(frq)")
    con.execute("CREATE INDEX idx_forms_form ON forms(form)")
    con.commit()
    con.execute("VACUUM")
    con.close()
    log("[ecdict] done", n, "entries", round(os.path.getsize(dst) / 1e6, 1), "MB")


# --------------------------------------------------------------------------- CEDICT
CJK = re.compile(r"[\u3400-\u9fff]")


def build_cedict():
    src = os.path.join(DL, "cedict.txt.gz")
    dst = os.path.join(OUT, "cedict.db")
    log("[cedict] building", dst)
    con = fresh(dst)
    con.executescript(
        """
        CREATE TABLE entries(
            id INTEGER PRIMARY KEY,
            trad TEXT NOT NULL,
            simp TEXT NOT NULL,
            pinyin TEXT,
            gloss TEXT
        );
        CREATE TABLE en_index(term TEXT NOT NULL, entry_id INTEGER NOT NULL);
        """
    )
    entries = []
    idx = []
    n = 0
    pattern = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/\s*$")
    with gzip.open(src, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            m = pattern.match(line.strip())
            if not m:
                continue
            trad, simp, pinyin, gloss = m.groups()
            eid = n + 1
            entries.append((eid, trad, simp, pinyin, gloss.replace("/", "\n")))
            terms = set()
            for gloss_part in gloss.split("/"):
                for term in re.split(r"[;,]", gloss_part):
                    t = term.strip()
                    if not t:
                        continue
                    terms.add(t)
                    if t.lower().startswith("to "):
                        terms.add(t[3:])
            for t in terms:
                if t.isascii():
                    idx.append((t.lower(), eid))
            n += 1
    con.executemany("INSERT INTO entries(id,trad,simp,pinyin,gloss) VALUES(?,?,?,?,?)", entries)
    con.executemany("INSERT INTO en_index(term,entry_id) VALUES(?,?)", idx)
    con.execute("CREATE INDEX idx_entries_simp ON entries(simp)")
    con.execute("CREATE INDEX idx_entries_trad ON entries(trad)")
    con.execute("CREATE INDEX idx_en_term ON en_index(term)")
    con.commit()
    con.execute("VACUUM")
    con.close()
    log("[cedict] done", n, "entries", len(idx), "index terms", round(os.path.getsize(dst) / 1e6, 1), "MB")


# --------------------------------------------------------------------------- WordNet
POS_NAMES = {"n": "noun", "v": "verb", "a": "adj", "s": "adj", "r": "adv"}


def parse_data(stream):
    """Yield (offset, pos, words[(lemma, lex_id)...], gloss, examples)."""
    for line in stream:
        line = line.rstrip("\n")
        if not line or line.startswith("  "):
            continue
        head, _, gloss = line.partition("|")
        gloss = gloss.strip()
        parts = head.split()
        if len(parts) < 6:
            continue
        offset = int(parts[0])
        ss_type = parts[2]
        w_cnt = int(parts[3], 16)
        words = []
        i = 4
        for _ in range(w_cnt):
            lemma = parts[i].replace("_", " ")
            lemma = re.sub(r"\([a-z]+\)$", "", lemma)
            words.append(lemma)
            i += 2
        # skip pointers
        try:
            p_cnt = int(parts[i], 16)
        except (IndexError, ValueError):
            continue
        examples = []
        definition = gloss
        if ";" in gloss:
            pieces = [p.strip() for p in gloss.split(";")]
            definition = pieces[0]
            examples = [p.strip(' "') for p in pieces[1:] if p.strip()]
        yield offset, ss_type, words, definition, examples


def build_wordnet():
    src = os.path.join(DL, "wordnet.zip")
    dst = os.path.join(OUT, "wordnet.db")
    log("[wordnet] building", dst)
    con = fresh(dst)
    con.executescript(
        """
        CREATE TABLE synsets(id INTEGER PRIMARY KEY, pos TEXT, definition TEXT, examples TEXT);
        CREATE TABLE senses(word TEXT NOT NULL, synset_id INTEGER NOT NULL, rank INTEGER DEFAULT 0);
        """
    )
    synsets = []
    senses = []
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        for pos in ("noun", "verb", "adj", "adv"):
            data_name = next((n for n in names if n.endswith("data." + pos)), None)
            idx_name = next((n for n in names if n.endswith("index." + pos)), None)
            if not data_name:
                continue
            sid = len(synsets) + 1
            offset_to_id = {}
            local = []
            with z.open(data_name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                for offset, ss_type, words, definition, examples in parse_data(text):
                    offset_to_id[offset] = sid
                    synsets.append((sid, POS_NAMES.get(ss_type, pos), definition, "\n".join(examples)))
                    for w in words:
                        local.append([w.lower(), sid, 0])
                    sid += 1
            # sense ranks from index file (offset order == sense number order)
            rank_map = {}
            if idx_name:
                with z.open(idx_name) as raw:
                    for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
                        if not line or line.startswith("  "):
                            continue
                        p = line.split()
                        if len(p) < 6:
                            continue
                        lemma = p[0].replace("_", " ").lower()
                        try:
                            offs = [int(x) for x in p[6:]]
                        except ValueError:
                            continue
                        for i, off in enumerate(offs):
                            s = offset_to_id.get(off)
                            if s:
                                rank_map[(lemma, s)] = i + 1
            for item in local:
                item[2] = rank_map.get((item[0], item[1]), 0)
                senses.append(tuple(item))
    con.executemany("INSERT INTO synsets(id,pos,definition,examples) VALUES(?,?,?,?)", synsets)
    con.executemany("INSERT INTO senses(word,synset_id,rank) VALUES(?,?,?)", senses)
    con.execute("CREATE INDEX idx_senses_word ON senses(word)")
    con.execute("CREATE INDEX idx_senses_syn ON senses(synset_id)")
    con.commit()
    con.execute("VACUUM")
    con.close()
    log("[wordnet] done", len(synsets), "synsets", len(senses), "senses", round(os.path.getsize(dst) / 1e6, 1), "MB")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    build_ecdict()
    build_cedict()
    build_wordnet()
    log("all done ->", OUT)
