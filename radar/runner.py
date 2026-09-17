# -*- coding: utf-8 -*-
"""한 사이클: 수집 → 스코어 → 중복제거 → 가격감시 → 문지기 → 슬랙·텔레그램."""
import hashlib
import html
from datetime import datetime

from radar import cluster, notify, score, sources, store, telegram
from radar.config import DATA_DIR, KST, in_quiet_hours, load_config

OUTBOX = DATA_DIR / "outbox"


def _noop(*_a, **_k):
    return None


def _pick_new(items, seen_this_run, ignore_seen=False):
    """DB 기준 처음 보는 것만 추린다. (등록은 전송 성공 후)"""
    keyed = []
    for it in items:
        k = store.norm_key(it.get("title", ""), it.get("url", ""))
        if k in seen_this_run:
            continue
        seen_this_run.add(k)
        keyed.append((k, it))
    if not keyed or ignore_seen:
        return keyed
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


def _new_result(mode, dry, started):
    return {"at": started.strftime("%Y-%m-%d %H:%M:%S KST"), "mode": mode, "dry": dry,
            "news_candidates": 0, "price_alerts": 0, "picked": 0, "sent": 0,
            "quiet": False, "first_run": False, "items": [], "error": None,
            "channels": [], "channel_errors": []}


def _gather(cfg, mode, dry, log, res):
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
    return candidates


def translate_all(items, translate, limit=40, log=print):
    """상위 기사 제목을 한국어로(사건 묶기용). 번역은 DB에 캐시해 같은 제목을 두 번 부르지 않는다."""
    n = 0
    for it in items[:limit]:
        if it.get("title_ko") or it.get("feed") == "price":
            continue
        t = it.get("title", "")
        ck = "tr:" + hashlib.sha1(t.encode("utf-8", "ignore")).hexdigest()
        ko = store.get_state(ck)
        if ko is None:
            ko = translate(t) or t
            n += 1
            if ko != t:
                store.set_state(ck, ko)
        it["title_ko"] = ko
    if n:
        log("  제목 번역 %d건" % n)


def dedupe_events(cfg, new, log=print):
    """같은 사건 묶기(이번 턴) + 최근 보낸 사건 거르기(지난 턴들). (남길 것, 접을 것) 반환."""
    items = [i for _, i in new]
    key_of = {id(i): k for k, i in new}
    kept, dropped = [], []
    for rep, dupes in cluster.group(items):
        srcs = []
        for d in dupes:
            if d.get("source") and d["source"] != rep.get("source") and d["source"] not in srcs:
                srcs.append(d["source"])
        rep["also"] = srcs
        # 여러 매체가 동시에 쓰면 큰 사건일 확률이 높다
        rep["score"] = min(100, rep["score"] + min(len(srcs), 3) * 3)
        kept.append((key_of[id(rep)], rep))
        dropped += [(key_of[id(d)], d) for d in dupes]
    if len(kept) < len(items):
        log("  같은 사건 묶기 %d → %d건" % (len(items), len(kept)))

    hours = cfg.get("repeat_block_hours", 18)
    recent = [(ko + cluster.SEP + t) if ko and ko != t else t for ko, t in store.recent_sent(hours)]
    if recent:
        fresh = []
        for k, i in kept:
            if i.get("feed") != "price" and cluster.seen_recently(cluster.key_of(i), recent):
                dropped.append((k, i))
            else:
                fresh.append((k, i))
        if len(fresh) < len(kept):
            log("  최근 %d시간 안에 보낸 사건 %d건 거름" % (hours, len(kept) - len(fresh)))
        kept = fresh
    kept.sort(key=lambda kv: kv[1]["score"], reverse=True)
    return kept, dropped


def _select(cfg, candidates, started, log, res, ignore_seen=False, translate=None):
    """중복제거 → 번역 → 같은 사건 묶기 → 조용시간 → 토픽 상한 → 전체 상한. (new, dropped) 반환."""
    new = _pick_new(candidates, set(), ignore_seen=ignore_seen)
    new.sort(key=lambda kv: kv[1]["score"], reverse=True)
    translate_all([i for _, i in new], translate or notify._ko, log=log)
    new, dup_dropped = dedupe_events(cfg, new, log=log)

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
    dropped = dup_dropped + overflow + new[cap:]
    new = new[:cap]
    res["picked"] = len(new)
    res["items"] = [{"score": i["score"], "topic": i.get("topic", ""),
                     "title": i.get("title", ""), "url": i.get("url", ""),
                     "source": i.get("source", "")} for _, i in new]
    return new, dropped


def cycle(mode="all", dry=False, log=print, cfg=None):
    """mode: all | news | price. dry=True 면 전송·DB기록 없이 결과만 반환."""
    cfg = cfg or load_config()
    started = datetime.now(KST)
    res = _new_result(mode, dry, started)

    if not dry and mode in ("all", "news"):
        try:
            from radar import kol
            kol.maybe_send(cfg, started, log=log)
        except Exception as e:  # 코너가 실패해도 뉴스 알림은 나간다
            log("  KOL 코너 실패(건너뜀): %s" % e)

    # 하루 1회 모드(강회장 요청 2026-09-18): 정해진 시각 이후 첫 턴에만 지난 24시간 뉴스를 모아 보낸다
    daily = cfg.get("news_daily") or {"enabled": True, "hour_kst": 8, "max_items": 8, "max_per_topic": 2}
    today = started.strftime("%Y-%m-%d")
    if daily.get("enabled") and mode in ("all", "news") and not dry:
        if started.hour < daily.get("hour_kst", 8) or store.get_state("news_daily_last") == today:
            log("  하루 1회 모드 — 오늘 발송 시각이 아니거나 이미 보냄")
            return res
        cfg = dict(cfg, lookback_hours=24, max_items_per_run=daily.get("max_items", 8),
                   max_per_topic=daily.get("max_per_topic", 2))

    candidates = _gather(cfg, mode, dry, log, res)
    new, dropped = _select(cfg, candidates, started, log, res)

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
        if daily.get("enabled"):
            store.set_state("news_daily_last", today)
        return res

    try:
        rep = notify.deliver(cfg, [i for _, i in new], log=log)
    except Exception as e:  # 전송 경로 자체가 없으면 seen 등록을 안 해야 다음 턴에 재시도된다
        res["error"] = str(e)
        log("  전송 실패 — seen 미등록(다음 턴 재시도): %s" % e)
        return res
    res = apply_report(res, new, dropped, rep, log=log)
    if daily.get("enabled") and res["sent"]:
        store.set_state("news_daily_last", today)
    return res


def apply_report(res, new, dropped, rep, log=print):
    """seen 등록 규칙 — 채널 중 **하나라도** 성공한 기사만 등록한다.

    둘 다 실패한 기사만 미등록(다음 턴 재시도). 한쪽만 성공했을 때 재시도하면
    성공한 쪽(예: 슬랙)에 15분마다 같은 기사가 계속 쌓이는 중복 폭탄이 되기 때문이다.
    실패한 채널의 누락은 channel_errors 로 남긴다.
    """
    ok_ids = {id(i) for i in rep["sent_items"]}
    ok = [(k, i) for k, i in new if id(i) in ok_ids]
    res["channels"] = rep.get("channels", [])
    res["channel_errors"] = rep.get("channel_errors", [])
    if ok:
        # 접힌 건(토픽/전체 상한)은 이번 알림이 실제로 나갔을 때만 같이 묻는다
        store.mark_seen([k for k, _ in ok] + [k for k, _ in dropped])
        store.log_sent([i for _, i in ok])
    res["sent"] = len(ok)
    if rep["failed_items"]:
        res["error"] = "모든 채널 전송 실패 %d건 — seen 미등록(다음 턴 재시도): %s" % (
            len(rep["failed_items"]), " / ".join(rep["channel_errors"])[:300])
        log("  " + res["error"])
    log("  전송 %d건 (채널: %s)" % (len(ok), ",".join(res["channels"]) or "-"))
    return res


# ─────────────────────────────────────────────────────────── 미리보기

def preview(cfg=None, log=print, out_dir=None, fetch_og=None, translate=None):
    """실제 수집 데이터로 슬랙·텔레그램 메시지를 만들어 파일로만 저장한다.

    전송 0, seen 등록 0, 직전가 기록 0(dry). 새 기사가 없으면 seen 을 무시한 후보로 대신 보여준다.
    """
    cfg = cfg or load_config()
    out_dir = out_dir or OUTBOX
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(KST)
    res = _new_result("all", True, started)
    candidates = _gather(cfg, "all", True, log, res)
    new, _ = _select(cfg, candidates, started, log, res, translate=translate)
    ignored_seen = False
    if not new and candidates:
        ignored_seen = True
        log("  새 기사가 없어 이미 본 기사까지 포함해 미리보기를 만듭니다")
        new, _ = _select(cfg, candidates, started, log, res, ignore_seen=True, translate=translate)

    kw = {"with_photo": True, "fetch_og": fetch_og}
    if translate:
        kw["translate"] = translate
    batches = notify.render_batches(cfg, [i for _, i in new], **kw)

    arts = [a for b in batches for a in b["msg"]["articles"]]
    stats = {
        "items": len(arts), "messages": len(batches),
        "photos": sum(1 for b in batches if b["photo"]),
        "rss_images": sum(1 for a in arts if a["image"]),
        "telegram_chunks": sum(len(b["telegram"]) for b in batches),
        "ignored_seen": ignored_seen,
    }
    html_path = out_dir / "preview_telegram.html"
    slack_path = out_dir / "preview_slack.txt"
    html_path.write_text(_preview_html(batches, stats, started), encoding="utf-8")
    slack_path.write_text(_preview_slack(batches, stats, started), encoding="utf-8")
    return {"html": str(html_path), "slack": str(slack_path), "stats": stats}


def _preview_slack(batches, stats, started):
    out = ["# 슬랙 미리보기 · %s KST · 메시지 %d개 / 기사 %d건%s" % (
        started.strftime("%Y-%m-%d %H:%M"), stats["messages"], stats["items"],
        " (새 기사가 없어 이미 본 기사 포함)" if stats["ignored_seen"] else "")]
    for n, b in enumerate(batches, 1):
        out.append("\n" + "=" * 70 + "\n[메시지 %d]\n" % n + "=" * 70)
        out.append(b["slack_text"])
    return "\n".join(out) + "\n"


def _preview_html(batches, stats, started):
    e = html.escape
    rows = []
    for n, b in enumerate(batches, 1):
        rows.append('<section class="msg"><h2>메시지 %d · %s</h2>' % (n, e(b["msg"]["header"])))
        if b["photo"]:
            rows.append('<div class="photo"><div class="lbl">sendPhoto · photo URL</div>'
                        '<a href="%s">%s</a><img src="%s" alt="">'
                        '<div class="lbl">caption (%d자)</div><pre>%s</pre><div class="tg">%s</div></div>'
                        % (e(b["photo"]), e(b["photo"]), e(b["photo"]), telegram.tg_len(b["caption"]),
                           e(b["caption"]), b["caption"]))
        else:
            rows.append('<div class="lbl">사진 없음 (RSS 이미지·og:image 모두 없음)</div>')
        for c, chunk in enumerate(b["telegram"], 1):
            rows.append('<div class="chunk"><div class="lbl">sendMessage %d/%d · %d자(UTF-16, 태그 포함)</div>'
                        '<div class="tg">%s</div><details><summary>HTML 원문</summary><pre>%s</pre></details></div>'
                        % (c, len(b["telegram"]), telegram.tg_len(chunk), chunk, e(chunk)))
        rows.append("</section>")
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>텔레그램 미리보기 — 뉴스 레이더</title>
<style>
body{font-family:system-ui,'Malgun Gothic',sans-serif;background:#0e1621;color:#e8eef4;margin:0;padding:16px}
main{max-width:760px;margin:0 auto}h1{font-size:18px}h2{font-size:15px;color:#8fb8e0}
.msg{border-top:1px solid #2b3a4a;padding:12px 0}.lbl{font-size:12px;color:#7f93a6;margin:8px 0 4px}
.tg{background:#182533;border-radius:10px;padding:10px 12px;white-space:pre-wrap;line-height:1.5}
.tg a{color:#6ab3f3}pre{white-space:pre-wrap;word-break:break-all;background:#0b1118;padding:8px;font-size:12px}
img{display:block;max-width:100%%;max-height:280px;margin:6px 0;border-radius:8px}.photo a{font-size:12px;color:#6ab3f3;word-break:break-all}
</style></head><body><main>
<h1>📰 세력의 정보원 — 텔레그램 미리보기</h1>
<p>%s KST 생성 · 메시지 %d개 · 기사 %d건 · 텔레그램 전송 단위 %d개 · 사진 %d/%d 메시지 · RSS 이미지 보유 기사 %d/%d%s</p>
<p class="lbl">전송·seen 등록 없이 만든 파일입니다. 실제 전송은 parse_mode=HTML, disable_web_page_preview=True, message_thread_id=TELEGRAM_TOPIC_NEWS 로 나갑니다.</p>
%s
</main></body></html>""" % (started.strftime("%Y-%m-%d %H:%M"), stats["messages"], stats["items"],
                            stats["telegram_chunks"], stats["photos"], stats["messages"],
                            stats["rss_images"], stats["items"],
                            " · <b>새 기사가 없어 이미 본 기사 포함</b>" if stats["ignored_seen"] else "",
                            "\n".join(rows))
