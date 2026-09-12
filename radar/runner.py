# -*- coding: utf-8 -*-
"""한 사이클: 수집 → 스코어 → 중복제거 → 가격감시 → 문지기 → 슬랙."""
from datetime import datetime

from radar import notify, score, sources, store
from radar.config import KST, in_quiet_hours, load_config


def _noop(*_a, **_k):
    return None


def _pick_new(items, seen_this_run):
    """DB 기준 처음 보는 것만 추린다. (등록은 전송 성공 후)"""
    keyed = []
    for it in items:
        k = store.norm_key(it.get("title", ""), it.get("url", ""))
        if k in seen_this_run:
            continue
        seen_this_run.add(k)
        keyed.append((k, it))
    if not keyed:
        return []
    fresh = store.is_new([k for k, _ in keyed])
    return [(k, it) for k, it in keyed if k in fresh]


def collect_news(cfg, log=print):
    """뉴스만 수집해서 점수순으로 반환(중복제거 전)."""
    raw = sources.collect(cfg, log=log)
    log("  수집 합계 %d건" % len(raw))
    return score.rank(raw, cfg)


def collect_price(cfg, dry=False, log=print):
    pw = cfg.get("price_watch", {})
    if not pw.get("enabled", True):
        return []
    picked, allrows = sources.binance_tickers(pw.get("symbols", []))
    if not picked and not allrows:
        log("  [시세] 조회 실패 — 건너뜀")
        return []
    getter = store.get_state
    setter = _noop if dry else store.set_state
    alerts = score.price_alerts(cfg, picked, allrows, getter, setter)
    log("  [시세] 워치 %d종목 / 전체 %d심볼 → 알림 후보 %d건"
        % (len(picked), len(allrows), len(alerts)))
    return alerts


def cycle(mode="all", dry=False, log=print, cfg=None):
    """mode: all | news | price. dry=True 면 전송·DB기록 없이 결과만 반환."""
    cfg = cfg or load_config()
    started = datetime.now(KST)
    res = {"at": started.strftime("%Y-%m-%d %H:%M:%S KST"), "mode": mode, "dry": dry,
           "news_candidates": 0, "price_alerts": 0, "picked": 0, "sent": 0,
           "quiet": False, "first_run": False, "items": [], "error": None}

    candidates = []
    if mode in ("all", "news"):
        scored = collect_news(cfg, log=log)
        min_score = cfg.get("min_score", 60)
        passed = [i for i in scored if i["score"] >= min_score]
        res["news_candidates"] = len(passed)
        log("  스코어 %d점 이상 %d건" % (min_score, len(passed)))
        candidates.extend(passed)

    if mode in ("all", "price"):
        pa = collect_price(cfg, dry=dry, log=log)
        res["price_alerts"] = len(pa)
        candidates.extend(pa)

    seen_this_run = set()
    new = _pick_new(candidates, seen_this_run)
    new.sort(key=lambda kv: kv[1]["score"], reverse=True)

    urgent_score = cfg.get("urgent_score", 85)
    if in_quiet_hours(cfg, started):
        res["quiet"] = True
        before = len(new)
        new = [(k, i) for k, i in new if i["score"] >= urgent_score]
        log("  조용시간 — 긴급건만 통과 (%d → %d)" % (before, len(new)))

    # 같은 사건을 여러 매체가 쓰면 제목 해시로는 안 잡힌다 → 토픽당 상한으로 도배 차단
    per_topic = cfg.get("max_per_topic", 3)
    kept, overflow, counts = [], [], {}
    for k, i in new:
        t = i.get("topic", "")
        counts[t] = counts.get(t, 0) + 1
        (kept if counts[t] <= per_topic else overflow).append((k, i))
    if overflow:
        log("  토픽 상한(%d) 초과 %d건 접음" % (per_topic, len(overflow)))
    new = kept

    cap = cfg.get("max_items_per_run", 12)
    dropped = overflow + new[cap:]
    new = new[:cap]
    res["picked"] = len(new)
    res["items"] = [{"score": i["score"], "topic": i.get("topic", ""),
                     "title": i.get("title", ""), "url": i.get("url", ""),
                     "source": i.get("source", "")} for _, i in new]

    if dry:
        log("  [dry-run] 전송 안 함 — 통과 %d건" % len(new))
        return res

    # 첫 실행은 과거 기사 폭탄을 막기 위해 조용히 학습만 한다
    if cfg.get("first_run_silent", True) and store.is_first_run():
        store.mark_seen([k for k, _ in new] + [k for k, _ in dropped])
        store.mark_initialized()
        res["first_run"] = True
        log("  첫 실행 — %d건을 조용히 학습(전송 생략)" % len(new))
        return res

    if not new:
        log("  보낼 것 없음")
        store.mark_seen([k for k, _ in dropped])
        return res

    try:
        sent = notify.deliver(cfg, [i for _, i in new], log=log)
    except Exception as e:  # 전송 실패 시 seen 등록을 안 해야 다음 턴에 재시도된다
        res["error"] = str(e)
        log("  전송 실패 — seen 미등록(다음 턴 재시도): %s" % e)
        return res

    store.mark_seen([k for k, _ in new] + [k for k, _ in dropped])
    store.log_sent([i for _, i in new])
    res["sent"] = sent
    log("  슬랙 전송 %d건" % sent)
    return res
