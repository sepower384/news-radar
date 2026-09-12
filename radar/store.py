# -*- coding: utf-8 -*-
"""중복 방지 + 상태 저장 (SQLite, 의존성 없음)."""
import hashlib
import os
import re
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "radar.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.execute("CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, ts INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT, ts INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS sent_log (ts INTEGER, score INTEGER, topic TEXT, title TEXT, url TEXT)")
    return c


# 매체마다 붙이는 머리표 — [속보] (단독) 【긴급】 등은 같은 사건 판정에서 지운다
_TAG = re.compile(r"^\s*(?:[\[\(<【（][^\]\)>】）]{0,12}[\]\)>】）]\s*)+")


def norm_key(title, url):
    """제목 정규화 해시 — 같은 사건을 여러 매체가 쓰면 URL이 달라도 상당수 잡힌다."""
    t = _TAG.sub("", title or "")
    t = "".join(ch for ch in t.lower() if ch.isalnum() or "가" <= ch <= "힣")
    # 12자 미만은 제목만으로 같은 사건이라 단정하기 어렵다 → URL까지 묶어서 구분
    base = t[:70] if len(t) >= 12 else (t + "|" + (url or ""))
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()


def is_new(keys):
    """키 목록 중 처음 보는 것만 돌려준다(등록은 mark_seen에서)."""
    if not keys:
        return set()
    c = _conn()
    try:
        q = "SELECT key FROM seen WHERE key IN (%s)" % ",".join("?" * len(keys))
        known = {r[0] for r in c.execute(q, list(keys))}
    finally:
        c.close()
    return {k for k in keys if k not in known}


def mark_seen(keys):
    if not keys:
        return
    now = int(time.time())
    c = _conn()
    try:
        c.executemany("INSERT OR IGNORE INTO seen VALUES (?,?)", [(k, now) for k in keys])
        c.execute("DELETE FROM seen WHERE ts < ?", (now - 30 * 86400,))
        c.commit()
    finally:
        c.close()


def log_sent(items):
    if not items:
        return
    now = int(time.time())
    c = _conn()
    try:
        c.executemany(
            "INSERT INTO sent_log VALUES (?,?,?,?,?)",
            [(now, int(i.get("score", 0)), i.get("topic", ""), i.get("title", "")[:300], i.get("url", "")) for i in items],
        )
        c.commit()
    finally:
        c.close()


def get_state(k, default=None):
    c = _conn()
    try:
        r = c.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
    finally:
        c.close()
    return r[0] if r else default


def set_state(k, v):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (k, str(v), int(time.time())))
        c.commit()
    finally:
        c.close()


def is_first_run():
    return get_state("initialized") is None


def mark_initialized():
    set_state("initialized", "1")
