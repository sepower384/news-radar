# -*- coding: utf-8 -*-
"""자체 검증. 네트워크 없이 도는 로직 테스트 + (옵션) 라이브 스모크.

    python tests/test_all.py          # 로직만 (빠름, 오프라인)
    python tests/test_all.py --live   # 실제 무료 소스까지 호출
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PYTHONUTF8", "1")

from radar import config, notify, score, sources, store  # noqa: E402
from radar.config import load_config  # noqa: E402

PASS = FAIL = 0
UTC = timezone.utc
CFG = load_config()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, detail))


def item(title, summary="", source="구글뉴스", feed="google", age_h=0.5, url=None):
    return {"title": title, "summary": summary, "source": source, "feed": feed,
            "url": url or ("https://x.test/%d" % abs(hash(title))),
            "published": datetime.now(UTC) - timedelta(hours=age_h)}


# --------------------------------- 파서 ---------------------------------
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>&lt;b&gt;\xec\x97\xb0\xec\xa4\x80&lt;/b&gt; \xea\xb8\xb0\xec\xa4\x80\xea\xb8\x88\xeb\xa6\xac 0.25%p \xec\x9d\xb8\xed\x95\x98 - \xec\x97\xb0\xed\x95\xa9\xeb\x89\xb4\xec\x8a\xa4</title>
<link>https://n.test/1</link><description>&lt;p&gt;\xed\x8c\x8c\xec\x9b\x94 \xec\x9d\x98\xec\x9e\xa5 \xeb\xb0\x9c\xed\x91\x9c&lt;/p&gt;</description>
<pubDate>Wed, 10 Sep 2026 01:00:00 GMT</pubDate></item>
<item><title>\xeb\x91\x90\xeb\xb2\x88\xec\xa7\xb8 \xea\xb8\xb0\xec\x82\xac</title><link>https://n.test/2</link>
<pubDate>Wed, 10 Sep 2026 02:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Fed holds rates steady</title><link href="https://a.test/1"/>
<summary>FOMC statement</summary><updated>2026-09-10T01:00:00Z</updated></entry></feed>"""


def test_parser():
    print("\n[파서]")
    rows = sources.parse_rss(RSS, "테스트")
    check("RSS 2건 파싱", len(rows) == 2, len(rows))
    check("HTML 태그 제거", "<b>" not in rows[0]["title"] and "연준" in rows[0]["title"])
    check("본문 엔티티 정리", rows[0]["summary"] == "파월 의장 발표", rows[0]["summary"])
    check("pubDate tz-aware", rows[0]["published"].tzinfo is not None)
    atom = sources.parse_rss(ATOM, "테스트")
    check("Atom 파싱", len(atom) == 1 and atom[0]["url"] == "https://a.test/1")
    check("깨진 XML 무해", sources.parse_rss(b"<not xml", "x") == [])
    check("_strip_html", sources._strip_html("<p>a&amp;b</p>") == "a&b")
    check("_parse_date None", sources._parse_date("") is None)
    old = [{"published": datetime.now(UTC) - timedelta(hours=30)}]
    check("lookback 컷", sources._fresh(old, 6) == [])
    check("published 없으면 통과", sources._fresh([{"published": None}], 6) != [])


# --------------------------------- 스코어 ---------------------------------
def test_score():
    print("\n[스코어]")
    topics = CFG["topics"]
    t, hits, w = score.match_topic(item("연준 기준금리 인하 발표"), topics)
    check("금리 토픽 매칭", t == "금리·통화정책", t)
    t2, _, _ = score.match_topic(item("Zcash ZEC 급등"), topics)
    check("ZEC 토픽 매칭", t2 == "지캐시(ZEC)", t2)
    t3, _, _ = score.match_topic(item("오늘 점심 메뉴 추천"), topics)
    check("무관 기사 탈락", t3 is None, t3)

    # 짧은 영문 티커는 단어경계로만 — hyperactive 같은 단어에 오탐 금지
    t4, _, _ = score.match_topic(item("Hyperactive kids study"), topics)
    check("hype 오탐 방지", t4 != "하이퍼리퀴드(HYPE)", t4)

    big = score.score_item(item("[속보] 연준 기준금리 0.5%p 전격 인하", source="연준(Fed) 공식",
                                feed="fed"), CFG)
    small = score.score_item(item("금리 인하 될까 전망 분석"), CFG)
    check("속보+공식소스 고득점", big["score"] >= CFG["urgent_score"], big["score"])
    check("전망/분석 노이즈 감점", small["score"] < big["score"], small["score"])
    check("점수 0~100 범위", 0 <= small["score"] <= 100)

    stale = score.score_item(item("연준 기준금리 인하", age_h=40), CFG)
    fresh = score.score_item(item("연준 기준금리 인하", age_h=0.2), CFG)
    check("신선도 가산", fresh["score"] > stale["score"], (fresh["score"], stale["score"]))

    notice = score.score_item(item("비트코인 네트워크 점검 안내", source="업비트 공지",
                                   feed="upbit"), CFG)
    strong = score.score_item(item("ABC 거래지원 종료(상장폐지) 안내", source="업비트 공지",
                                   feed="upbit"), CFG)
    check("공지 잡음 감점", strong["score"] > notice["score"], (strong["score"], notice["score"]))
    check("코인명 없는 상장폐지 공지도 건짐", strong["topic"] == "코인 전반·규제", strong["topic"])
    check("무관 공지는 여전히 탈락",
          score.score_item(item("서버 점검 안내", source="업비트 공지", feed="upbit"), CFG) is None)

    numeric = score.score_item(item("비트코인 12% 급락 청산 30억 달러"), CFG)
    check("수치 제목 가산", numeric["score"] > 0)
    ranked = score.rank([item("오늘 날씨"), item("[속보] 이란 호르무즈 해협 봉쇄")], CFG)
    check("rank 무관건 제외", len(ranked) == 1 and ranked[0]["topic"] == "호르무즈·지정학")


# --------------------------------- 가격 감시 ---------------------------------
def test_price():
    print("\n[가격 감시]")
    mem = {}

    def get(k, d=None):
        return mem.get(k, d)

    def setf(k, v):
        mem[k] = str(v)

    picked = {"BTCUSDT": {"symbol": "BTCUSDT", "price": 100000.0, "pct24h": 1.0,
                          "quote_vol": 1e9}}
    first = score.price_alerts(CFG, picked, [], get, setf)
    check("첫 관측은 알림 없음", first == [])
    check("직전가 저장됨", mem.get("px:BTCUSDT") == "100000.0", mem.get("px:BTCUSDT"))

    picked["BTCUSDT"]["price"] = 105000.0       # +5% > 임계 2.5%
    second = score.price_alerts(CFG, picked, [], get, setf)
    check("단기 급등 감지", len(second) == 1 and "급등" in second[0]["title"], second)
    check("급등 알림 점수 >= min", second and second[0]["score"] >= CFG["min_score"])

    picked["BTCUSDT"]["price"] = 105100.0       # +0.1% — 임계 미만
    check("미세 변동 무시", score.price_alerts(CFG, picked, [], get, setf) == [])

    mem.clear()
    p24 = {"ETHUSDT": {"symbol": "ETHUSDT", "price": 4000.0, "pct24h": -12.0, "quote_vol": 1e9}}
    a = score.price_alerts(CFG, p24, [], get, setf)
    check("24h 급변 감지", len(a) == 1 and "24시간" in a[0]["title"], a)
    check("같은 시간대 재알림 차단", score.price_alerts(CFG, p24, [], get, setf) == [])

    mem.clear()
    rows = [{"symbol": "AAAUSDT", "price": 1.0, "pct24h": 40.0, "quote_vol": 5e7},
            {"symbol": "BBBUSDT", "price": 1.0, "pct24h": 90.0, "quote_vol": 1e5}]
    scan = score.price_alerts(CFG, {}, rows, get, setf)
    syms = [s["title"].split()[0] for s in scan]
    check("시장 스캔 감지", "AAA" in syms, syms)
    check("거래대금 미달 제외", "BBB" not in syms, syms)

    off = dict(CFG)
    off["price_watch"] = dict(CFG["price_watch"], enabled=False)
    check("enabled=false 면 무동작", score.price_alerts(off, picked, rows, get, setf) == [])


# --------------------------------- 저장소 ---------------------------------
def test_store():
    print("\n[저장소]")
    old = store.DB_PATH
    store.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    try:
        k1 = store.norm_key("연준, 기준금리 0.25%p 전격 인하 결정", "https://a.test/1")
        k2 = store.norm_key("[속보] 연준 기준금리 0.25%p 전격 인하 결정!", "https://b.test/2")
        check("매체 달라도 같은 사건 인식", k1 == k2)
        s1 = store.norm_key("금리 인하", "https://a.test/1")
        s2 = store.norm_key("금리 인하", "https://b.test/2")
        check("짧은 제목은 URL로 구분", s1 != s2)
        k3 = store.norm_key("완전히 다른 사건이 벌어졌다고 한다", "https://c.test/3")
        check("다른 기사 구분", k3 != k1)

        check("처음엔 전부 신규", store.is_new([k1, k3]) == {k1, k3})
        store.mark_seen([k1])
        check("등록 후 중복 차단", store.is_new([k1, k3]) == {k3})
        check("빈 입력 안전", store.is_new([]) == set())

        check("첫 실행 플래그", store.is_first_run() is True)
        store.mark_initialized()
        check("초기화 후 해제", store.is_first_run() is False)
        store.set_state("px:X", 1.5)
        check("state 저장/조회", store.get_state("px:X") == "1.5")
        check("state 기본값", store.get_state("없음", "d") == "d")
        store.log_sent([{"score": 90, "topic": "t", "title": "제목", "url": "u"}])
        check("전송로그 기록", True)
    finally:
        store.DB_PATH = old


# --------------------------------- 알림 포맷 ---------------------------------
def test_notify():
    print("\n[알림 포맷]")
    it = score.score_item(item("[속보] 연준 기준금리 인하", source="연준(Fed) 공식", feed="fed"), CFG)
    blocks = notify.build_blocks([it], CFG["urgent_score"], "테스트")
    check("header 블록", blocks[0]["type"] == "header")
    check("context 꼬리", blocks[-1]["type"] == "context")
    check("divider 안 남김", blocks[-2]["type"] != "divider")
    body = blocks[1]["text"]["text"]
    check("링크 mrkdwn", "<https://" in body and "|" in body)
    check("꺾쇠 이스케이프", "&lt;" in notify._line(dict(it, title="<script>"), 85))
    e, tier = notify._tier(95, 85)
    check("긴급 티어", tier == "긴급" and e == "🚨")
    check("참고 티어", notify._tier(61, 85)[1] == "참고")
    check("published None 안전", "score" in notify._line(dict(it, published=None), 85))
    check("백엔드 판정 none",
          notify.backend_of({"slack": {"mode": "webhook", "webhook_url": ""}}) == "none")
    check("백엔드 판정 webhook",
          notify.backend_of({"slack": {"mode": "webhook", "webhook_url": "https://h"}}) == "webhook")
    check("백엔드 판정 playwright",
          notify.backend_of({"slack": {"mode": "pw", "playwright": {"channel_url": "https://s"}}}) == "playwright")


# --------------------------------- 설정·사이클 ---------------------------------
def test_config_and_cycle():
    print("\n[설정·사이클]")
    check("토픽 8개", len(CFG["topics"]) == 8, len(CFG["topics"]))
    ok = True
    for name, t in CFG["topics"].items():
        if not (t.get("queries") and t.get("keywords") and t.get("weight")):
            ok = False
            check("토픽 스키마 %s" % name, False)
            break
    if ok:
        check("모든 토픽 스키마 정상", True)
    check("임계값 순서", CFG["min_score"] < CFG["urgent_score"])
    kst_now = datetime(2026, 9, 10, 3, 0, tzinfo=config.KST)
    check("조용시간 없음=False", config.in_quiet_hours({"quiet_hours": []}, kst_now) is False)
    check("조용시간 적중", config.in_quiet_hours({"quiet_hours": [2, 3, 4]}, kst_now) is True)
    check("조용시간 비적중", config.in_quiet_hours({"quiet_hours": [9]}, kst_now) is False)

    from radar import runner
    fake = [item("[속보] 이란 호르무즈 해협 전면 봉쇄"), item("오늘 점심 뭐 먹지"),
            item("비트코인 시황 분석 될까")]
    orig = sources.collect
    sources.collect = lambda cfg, log=print: fake
    try:
        cfg_news = dict(CFG)
        cfg_news["price_watch"] = dict(CFG["price_watch"], enabled=False)
        res = runner.cycle("news", dry=True, log=lambda m: None, cfg=cfg_news)
    finally:
        sources.collect = orig
    titles = [i["title"] for i in res["items"]]
    check("dry-run 전송 안 함", res["sent"] == 0 and res["dry"] is True)
    check("큰 건만 통과", any("호르무즈" in t for t in titles), titles)
    check("잡담 탈락", not any("점심" in t for t in titles), titles)

    dup = [item("[속보] 이란 호르무즈 해협 전면 봉쇄", url="https://x.test/dup") for _ in range(3)]
    seen = set()
    check("같은 사건 1건으로 축약", len(runner._pick_new(dup, seen)) <= 1)

    # 같은 사건을 매체마다 다르게 쓰면 해시로는 못 잡는다 → 토픽 상한이 도배를 막는다
    flood = [item("연준 기준금리 인상 확률 %d%% 급등 전격 결정 발표" % n) for n in range(80, 99)]
    orig2 = sources.collect
    sources.collect = lambda cfg, log=print: flood
    try:
        cfg2 = dict(cfg_news)
        cfg2["max_per_topic"] = 3
        res2 = runner.cycle("news", dry=True, log=lambda m: None, cfg=cfg2)
    finally:
        sources.collect = orig2
    check("토픽 상한 적용", res2["picked"] == 3, res2["picked"])
    check("상한 안에서 고득점 우선",
          res2["items"] == sorted(res2["items"], key=lambda i: -i["score"]))


# --------------------------------- 단일 인스턴스 ---------------------------------
def test_single_instance():
    print("\n[단일 인스턴스]")
    import subprocess
    root = str(Path(__file__).resolve().parent.parent)
    code = ("import sys; sys.path.insert(0, r'%s'); import watch; "
            "print(watch.acquire_single_instance(), flush=True)" % root)
    p1 = subprocess.Popen([sys.executable, "-c", code + "; import time; time.sleep(6)"],
                          stdout=subprocess.PIPE, text=True)
    try:
        first = (p1.stdout.readline() or "").strip()
        second = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, timeout=30).stdout.strip()
        check("첫 인스턴스는 잠금 획득", first == "True", first)
        check("두번째 인스턴스는 차단", second == "False", second)
    finally:
        p1.kill()
        p1.wait(timeout=10)
    third = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=30).stdout.strip()
    check("죽으면 잠금 해제", third == "True", third)


# --------------------------------- 라이브 ---------------------------------
def test_live():
    print("\n[라이브 — 실제 네트워크]")
    g = sources.google_news("기준금리", "ko")
    check("구글뉴스 수집", len(g) > 3, len(g))
    check("구글뉴스 매체명 분리", any(i["source"] != "구글뉴스" for i in g))
    picked, rows = sources.binance_tickers(["BTCUSDT"])
    check("바이낸스 시세", picked.get("BTCUSDT", {}).get("price", 0) > 1000)
    check("USDT 마켓 전체", len(rows) > 200, len(rows))
    check("연준 RSS", len(sources.simple_rss(*sources.RSS_FEEDS["fed"])) > 0)


def main():
    test_parser()
    test_score()
    test_price()
    test_store()
    test_notify()
    test_config_and_cycle()
    test_single_instance()
    if "--live" in sys.argv:
        test_live()
    print("\n%s\n결과: %d PASS / %d FAIL\n%s" % ("=" * 46, PASS, FAIL, "=" * 46))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
