# -*- coding: utf-8 -*-
"""중요도 스코어링 — '큰 것만' 통과시키는 문지기."""
import re
from datetime import datetime, timezone

# 공식 발표처는 그 자체로 무게가 다르다
SOURCE_BONUS = {
    "연준(Fed) 공식": 25,
    "바이낸스 공지": 18,
    "업비트 공지": 18,
    "The Block": 8,
    "CoinDesk": 6,
    "Cointelegraph": 3,
}

# 공지 제목 안에서만 의미가 큰 신호
NOTICE_STRONG = ["상장폐지", "거래지원 종료", "유의종목", "입출금 중단", "delist", "will delist",
                 "suspension", "suspend", "halt", "network upgrade", "hard fork", "투자유의"]


def _hay(item):
    return ("%s %s" % (item.get("title", ""), item.get("summary", ""))).lower()


def kw_in(k, text):
    """키워드 포함 여부. 짧은 영단어는 단어 단위로만(war→software, ban→urban, ath→death 오탐 방지)."""
    k = k.lower()
    if re.fullmatch(r"[a-z]+", k) and len(k) <= 5:
        return re.search(r"\b%s(?:s|es|ed|ing)?\b" % re.escape(k), text) is not None
    if re.fullmatch(r"[a-z][a-z ]*", k):
        return re.search(r"\b%s" % re.escape(k), text) is not None
    return k in text


def match_topic(item, topics):
    """가장 잘 맞는 토픽과 매칭 강도를 돌려준다. 아무 토픽에도 안 걸리면 None.

    제목에 걸린 키워드는 2점, 본문에만 걸린 키워드는 1점이다.
    본문 요약에 '이란'이 한 번 나온 해커 기사가 '호르무즈 긴급'이 되는 일을 막는다(2026-09-17 실측).
    반환: (토픽, 강도, 가중치, 제목 적중 수)
    """
    title = (item.get("title") or "").lower()
    hay = _hay(item)
    best, best_hits, best_w, best_t = None, 0, 0, 0
    for name, t in topics.items():
        hits = t_hits = 0
        for kw in t.get("keywords", []):
            if kw_in(kw, title):
                hits += 2
                t_hits += 1
            elif kw_in(kw, hay):
                hits += 1
        if hits:
            w = t.get("weight", 15)
            if hits * w > best_hits * best_w:
                best, best_hits, best_w, best_t = name, hits, w, t_hits
    if not best:
        return None, 0, 0, 0
    return best, best_hits, best_w, best_t


def score_item(item, cfg):
    topics = cfg.get("topics", {})
    topic, hits, weight, title_hits = match_topic(item, topics)
    hay = _hay(item)

    # 거래소 공지는 코인명을 몰라도 "상장폐지·입출금 중단" 자체가 신호다
    if not topic and item.get("feed") in ("binance", "upbit"):
        if any(n in hay for n in NOTICE_STRONG):
            topic = "코인 전반·규제"
            hits, weight, title_hits = 2, topics.get(topic, {}).get("weight", 18), 1

    if not topic:
        return None

    title_l = item.get("title", "").lower()

    s = weight + min(hits, 8) * 3            # 토픽 적합도(제목 적중 2점, 본문 1점)
    s += SOURCE_BONUS.get(item.get("source"), 0)
    s += SOURCE_BONUS.get(item.get("feed"), 0)

    # 긴급도 키워드 — 제목에 있으면 만점, 본문에만 있으면 절반
    fired = []
    for kw, pts in cfg.get("urgency_keywords", {}).items():
        if kw_in(kw, title_l):
            s += pts
            fired.append(kw)
        elif kw_in(kw, hay):
            s += pts // 2

    # 제목에 주제어가 하나도 없으면 '곁가지' 기사 — 긴급으로 올리지 않는다
    if not title_hits:
        s -= 12
        s = min(s, cfg.get("urgent_score", 85) - 1)

    # 거래소 공지는 "상장/폐지/중단"류만 의미 있음
    if item.get("feed") in ("binance", "upbit"):
        if any(n in hay for n in NOTICE_STRONG):
            s += 20
        else:
            s -= 25

    # 노이즈(전망·분석·추천글) 감점
    for nk in cfg.get("noise_keywords", []):
        if kw_in(nk, title_l):
            s -= 14

    # 숫자(수치·규모)가 든 제목은 사실 보도일 확률이 높다
    if re.search(r"\d+(\.\d+)?\s*(%|억|조|만|billion|million|bp)", title_l):
        s += 6

    # 신선도
    pub = item.get("published")
    if pub:
        age_h = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        if age_h <= 1:
            s += 12
        elif age_h <= 3:
            s += 6
        elif age_h > 12:
            s -= 10

    out = dict(item)
    out["topic"] = topic
    if not title_hits:
        s = min(s, cfg.get("urgent_score", 85) - 1)
    out["score"] = int(max(0, min(100, s)))
    out["fired"] = fired[:4]
    return out


def rank(items, cfg):
    scored = []
    for it in items:
        r = score_item(it, cfg)
        if r:
            scored.append(r)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ---------------------------------------------------------------- 가격 급변

def price_alerts(cfg, picked, allrows, get_state, set_state):
    """워치리스트 단기 급변 + 시장 전체 급등락 스캔."""
    pw = cfg.get("price_watch", {})
    if not pw.get("enabled", True):
        return []
    alerts = []
    short_th = pw.get("spike_pct_short", 2.5)
    d24_th = pw.get("spike_pct_24h", 8.0)

    for sym, row in picked.items():
        name = sym.replace("USDT", "")
        price, p24 = row["price"], row["pct24h"]
        prev = get_state("px:" + sym)
        set_state("px:" + sym, price)
        if prev:
            try:
                prev = float(prev)
            except ValueError:
                prev = 0
            if prev > 0:
                move = (price - prev) / prev * 100
                if abs(move) >= short_th:
                    up = move > 0
                    alerts.append({
                        "title": "%s %s%.2f%% (직전 체크 대비 급%s) — 현재 $%s / 24h %+.2f%%"
                                 % (name, "+" if up else "", move, "등" if up else "락",
                                    _fmt(price), p24),
                        "url": "https://www.binance.com/en/trade/%s_USDT" % name,
                        "summary": "",
                        "source": "바이낸스 시세",
                        "feed": "price",
                        "topic": "가격 급변",
                        "published": datetime.now(timezone.utc),
                        "score": min(100, 70 + int(abs(move) * 4)),
                        "fired": ["급등" if up else "급락"],
                    })
                    continue
        if abs(p24) >= d24_th:
            key = "d24:%s:%s" % (sym, datetime.now(timezone.utc).strftime("%Y%m%d%H"))
            if not get_state(key):
                set_state(key, "1")
                alerts.append({
                    "title": "%s 24시간 %+.2f%% — 현재 $%s" % (name, p24, _fmt(price)),
                    "url": "https://www.binance.com/en/trade/%s_USDT" % name,
                    "summary": "",
                    "source": "바이낸스 시세",
                    "feed": "price",
                    "topic": "가격 급변",
                    "published": datetime.now(timezone.utc),
                    "score": min(100, 62 + int(abs(p24) * 2)),
                    "fired": ["24h 급변"],
                })

    if pw.get("market_scan", True) and allrows:
        th = pw.get("market_scan_pct", 15.0)
        minvol = pw.get("market_scan_min_quote_vol", 30000000)
        movers = [r for r in allrows if abs(r["pct24h"]) >= th and r["quote_vol"] >= minvol]
        movers.sort(key=lambda r: abs(r["pct24h"]), reverse=True)
        for r in movers[:5]:
            sym = r["symbol"]
            key = "scan:%s:%s" % (sym, datetime.now(timezone.utc).strftime("%Y%m%d%H"))
            if get_state(key):
                continue
            set_state(key, "1")
            alerts.append({
                "title": "%s 24시간 %+.2f%% (거래대금 $%.0fM) — 시장 급변 감지"
                         % (sym.replace("USDT", ""), r["pct24h"], r["quote_vol"] / 1e6),
                "url": "https://www.binance.com/en/trade/%s_USDT" % sym.replace("USDT", ""),
                "summary": "",
                "source": "바이낸스 시세",
                "feed": "price",
                "topic": "코인 급등락 스캔",
                "published": datetime.now(timezone.utc),
                "score": min(100, 60 + int(abs(r["pct24h"]))),
                "fired": ["시장 스캔"],
            })
    return alerts


def _fmt(p):
    if p >= 1000:
        return "{:,.0f}".format(p)
    if p >= 1:
        return "{:,.2f}".format(p)
    return "{:.6f}".format(p).rstrip("0")
