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
# 시세 로직 테스트는 설정의 on/off 와 무관하게 돌아야 한다(운영에선 꺼둘 수 있음)
PX_CFG = dict(CFG, price_watch=dict(CFG.get("price_watch", {}), enabled=True))


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
    first = score.price_alerts(PX_CFG, picked, [], get, setf)
    check("첫 관측은 알림 없음", first == [])
    check("직전가 저장됨", mem.get("px:BTCUSDT") == "100000.0", mem.get("px:BTCUSDT"))

    picked["BTCUSDT"]["price"] = 105000.0       # +5% > 임계 2.5%
    second = score.price_alerts(PX_CFG, picked, [], get, setf)
    check("단기 급등 감지", len(second) == 1 and "급등" in second[0]["title"], second)
    check("급등 알림 점수 >= min", second and second[0]["score"] >= PX_CFG["min_score"])

    picked["BTCUSDT"]["price"] = 105100.0       # +0.1% — 임계 미만
    check("미세 변동 무시", score.price_alerts(PX_CFG, picked, [], get, setf) == [])

    mem.clear()
    p24 = {"ETHUSDT": {"symbol": "ETHUSDT", "price": 4000.0, "pct24h": -12.0, "quote_vol": 1e9}}
    a = score.price_alerts(PX_CFG, p24, [], get, setf)
    check("24h 급변 감지", len(a) == 1 and "24시간" in a[0]["title"], a)
    check("같은 시간대 재알림 차단", score.price_alerts(PX_CFG, p24, [], get, setf) == [])

    mem.clear()
    rows = [{"symbol": "AAAUSDT", "price": 1.0, "pct24h": 40.0, "quote_vol": 5e7},
            {"symbol": "BBBUSDT", "price": 1.0, "pct24h": 90.0, "quote_vol": 1e5}]
    scan = score.price_alerts(PX_CFG, {}, rows, get, setf)
    syms = [s["title"].split()[0] for s in scan]
    check("시장 스캔 감지", "AAA" in syms, syms)
    check("거래대금 미달 제외", "BBB" not in syms, syms)

    off = dict(PX_CFG)
    off["price_watch"] = dict(PX_CFG["price_watch"], enabled=False)
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
    check("안내 문구", blocks[1]["type"] == "context")
    body = blocks[2]["text"]["text"]
    check("링크 mrkdwn", "<https://" in body and "|" in body)
    check("왜 중요한지 설명", notify.WHY_LABEL in body and "때문입니다" in body, body)
    check("꺾쇠 이스케이프", "&lt;" in notify._line(dict(it, title="<script>"), 85))
    e, tier = notify._tier(95, 85)
    check("긴급 티어", tier == "긴급" and e == "🚨")
    check("참고 티어", notify._tier(61, 85)[1] == "참고")
    check("published None 안전", "중요도" in notify._line(dict(it, published=None), 85))
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
    os.environ["SLACK_WEBHOOK_URL"] = "https://example.invalid/hook"
    try:
        forced = load_config()
    finally:
        del os.environ["SLACK_WEBHOOK_URL"]
    check("환경변수 웹훅이면 모드 강제 webhook", forced["slack"]["mode"] == "webhook"
          and notify.backend_of(forced) == "webhook", forced["slack"].get("mode"))
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


# --------------------------------- 텔레그램 ---------------------------------
TG_ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_NEWS", "TELEGRAM_CHAT_ID", "TELEGRAM_TOPIC_NEWS")


class _Env:
    """테스트 동안만 환경변수를 바꾸고 원래대로 되돌린다."""

    def __init__(self, **kv):
        self.kv, self.old = kv, {}

    def __enter__(self):
        for k in set(TG_ENV) | set(self.kv):
            self.old[k] = os.environ.pop(k, None)
        for k, v in self.kv.items():
            if v is not None:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


class _Resp:
    def __init__(self, status, js):
        self.status_code, self._js, self.text = status, js, str(js)

    def json(self):
        return self._js


def test_telegram():
    print("\n[텔레그램]")
    from radar import telegram as tg

    # 토큰 선택: 스트림 전용(_NEWS) → 공용 순
    with _Env(TELEGRAM_BOT_TOKEN="shared", TELEGRAM_BOT_TOKEN_NEWS="news-only",
              TELEGRAM_CHAT_ID="-1001", TELEGRAM_TOPIC_NEWS="7"):
        check("스트림 전용 토큰 우선", tg.settings() == ("news-only", "-1001", "7"), tg.settings())
    with _Env(TELEGRAM_BOT_TOKEN="shared", TELEGRAM_CHAT_ID="-1001"):
        check("전용 토큰 없으면 공용 토큰", tg.settings()[0] == "shared" and tg.enabled())
    with _Env(TELEGRAM_BOT_TOKEN_NEWS="news-only", TELEGRAM_CHAT_ID="-1001"):
        check("전용 토큰만 있어도 켜짐", tg.enabled() and tg.settings()[0] == "news-only")
    with _Env(TELEGRAM_BOT_TOKEN_NEWS=" ", TELEGRAM_BOT_TOKEN="shared", TELEGRAM_CHAT_ID="-1001"):
        check("빈칸 전용 토큰은 무시", tg.settings()[0] == "shared")
    with _Env(TELEGRAM_BOT_TOKEN="shared"):
        check("채팅 ID 없으면 꺼짐", tg.enabled() is False)
    with _Env():
        check("변수 없으면 조용히 꺼짐", tg.enabled() is False)
        check("변수 없으면 채널 목록에서 빠짐",
              notify.channels({"slack": {"mode": "webhook", "webhook_url": ""}}) == [])

    # 이스케이프·이모지·변환
    check("HTML 이스케이프", tg.esc("a&b<c>") == "a&amp;b&lt;c&gt;", tg.esc("a&b<c>"))
    check("이모지 코드 매핑", tg.emoji_codes_to_unicode(":rotating_light: :point_right: :clock3:")
          == "🚨 👉 🕒")
    check("모르는 이모지 코드는 유지", tg.emoji_codes_to_unicode(":no_such_code:") == ":no_such_code:")
    import re as _re
    codes = set()
    for p in Path(__file__).resolve().parent.parent.joinpath("radar").glob("*.py"):
        if p.name == "telegram.py":
            continue
        codes |= set(_re.findall(r"(?<![\w:/]):([a-z][a-z0-9_+\-]{2,}):(?![\w/])", p.read_text(encoding="utf-8")))
    check("코드베이스 슬랙 이모지 코드 전부 매핑", all(c in tg.EMOJI_MAP for c in codes), codes)
    h = tg.slack_to_html("*굵게* _기울임_ `*코드*` <https://x.test/?a=1&amp;b=2|링크 &amp; 글> &lt;script&gt; :bulb:")
    check("굵게 변환", "<b>굵게</b>" in h, h)
    check("기울임 변환", "<i>기울임</i>" in h, h)
    check("코드 안은 굵게 변환 안 함", "<code>*코드*</code>" in h, h)
    check("링크 변환+속성 이스케이프", '<a href="https://x.test/?a=1&amp;b=2">링크 &amp; 글</a>' in h, h)
    check("슬랙 엔티티 → 텔레그램 이스케이프 유지", "&lt;script&gt;" in h and "<script>" not in h, h)
    check("변환 시 이모지 매핑", h.endswith("💡"), h)

    # 분할
    check("UTF-16 길이(이모지=2)", tg.tg_len("🚨a") == 3)
    blocks = ['<b>기사 %d</b>\n<a href="https://x.test/%d">%s</a>' % (n, n, "가" * 600) for n in range(20)]
    parts = tg.split_html(blocks)
    check("4096자 이하로 분할", len(parts) > 1 and all(tg.tg_len(p) <= tg.MAX_TEXT for p in parts),
          [tg.tg_len(p) for p in parts])
    check("기사 경계에서만 분할(내용 보존)", "\n\n".join(parts) == "\n\n".join(blocks))
    check("분할 조각마다 태그 짝 맞음", all(p.count("<b>") == p.count("</b>") and
                                    p.count("<a ") == p.count("</a>") for p in parts))
    check("문자열은 빈 줄 경계로 분할", tg.split_html("a\n\nb", limit=2) == ["a", "b"])
    huge = tg.split_html(["<b>" + "나&" * 4000 + "</b>"])
    check("초대형 한 줄도 태그 안 깨짐", all(tg.tg_len(p) <= tg.MAX_TEXT and not _re.search(r"<[^>]*$", p)
                                      and not _re.search(r"&[a-z]*$", p) for p in huge), len(huge))
    cap = tg.clip_caption("<b>" + "가" * 2000 + "</b>")
    check("캡션 1024자 제한", tg.tg_len(cap) <= tg.MAX_CAPTION and "<b>" not in cap)

    # 전송(가짜 서버): 429 재시도, 사진 실패 무시, 페이로드
    calls, sleeps = [], []
    orig_post, orig_sleep = tg._post, tg._sleep
    tg._sleep = lambda s: sleeps.append(s)
    try:
        seq = [_Resp(429, {"ok": False, "parameters": {"retry_after": 2}}), _Resp(200, {"ok": True})]
        tg._post = lambda url, json=None, timeout=None: (calls.append((url, json)), seq.pop(0))[1]
        with _Env(TELEGRAM_BOT_TOKEN="T", TELEGRAM_CHAT_ID="-100123", TELEGRAM_TOPIC_NEWS="42"):
            tg.send_message("<b>hi</b>")
        check("429 면 retry_after 만큼 쉬고 재시도", len(calls) == 2 and sleeps == [2.0], (len(calls), sleeps))
        p = calls[-1][1]
        check("sendMessage 페이로드", p.get("message_thread_id") == 42 and p.get("parse_mode") == "HTML"
              and p.get("disable_web_page_preview") is True and p.get("chat_id") == "-100123", p)

        tg._post = lambda url, json=None, timeout=None: _Resp(429, {"ok": False, "parameters": {"retry_after": 1}})
        try:
            with _Env(TELEGRAM_BOT_TOKEN="T", TELEGRAM_CHAT_ID="-1"):
                tg.send_message("x")
            check("429 두 번이면 실패 처리", False)
        except RuntimeError:
            check("429 두 번이면 실패 처리", True)

        calls.clear()
        sleeps.clear()

        def fake(url, json=None, timeout=None):
            calls.append(url.rsplit("/", 1)[-1])
            if url.endswith("sendPhoto"):
                raise TimeoutError("사진 시간초과")
            return _Resp(200, {"ok": True})
        tg._post = fake
        with _Env(TELEGRAM_BOT_TOKEN="T", TELEGRAM_CHAT_ID="-1"):
            n = tg.send(["a", "b"], photo="https://img.test/a.jpg", caption="c", log=lambda m: None)
        check("사진 실패해도 본문 전송", n == 2 and calls == ["sendPhoto", "sendMessage", "sendMessage"], calls)
        check("메시지 사이 1초", 1 in sleeps, sleeps)
    finally:
        tg._post, tg._sleep = orig_post, orig_sleep


# --------------------------------- 말투·용어 ---------------------------------
HAEYO = __import__("re").compile(r"(해요|이에요|예요|어요|아요|워요|세요|네요|래요|대요|죠)(?=[\s.!?,…)\"'<*_]|$)")


def _fake_items():
    now = datetime.now(UTC)
    out = []
    for n, topic in enumerate(notify.TOPIC_WHY):
        out.append({"title": "연준 FOMC 25bp 인하에 ETF 자금 유입 %d" % n, "url": "https://n.test/%d" % n,
                    "source": "연합뉴스", "feed": "google", "topic": topic, "published": now,
                    "score": 90 if n == 0 else 70, "image": ""})
    return out


def test_tone_and_glossary():
    print("\n[말투·용어]")
    from radar import glossary as g
    check("모든 '중요한 이유'가 합니다체", all(v.endswith("니다.") for v in notify.TOPIC_WHY.values()))
    msgs = notify.render_batches(CFG, _fake_items(), with_photo=False, translate=lambda t: t)
    texts = []
    for b in msgs:
        texts.append(b["slack_text"])
        texts.extend(b["telegram"])
        texts.extend(blk["text"]["text"] for blk in b["slack_blocks"] if blk.get("text"))
        texts.extend(el["text"] for blk in b["slack_blocks"] for el in blk.get("elements", []))
    left = [m.group(0) for t in texts for m in HAEYO.finditer(t)]
    check("메시지에 해요체 어미 없음", not left, left[:5])
    check("합니다체 문장 존재", all("니다" in t for t in texts if len(t) > 80))
    ping_src = Path(__file__).resolve().parent.parent.joinpath("radar", "notify.py").read_text(encoding="utf-8")
    check("notify.py 문자열에 해요체 없음", not HAEYO.search(ping_src), HAEYO.findall(ping_src)[:5])

    used = set()
    s = g.annotate("연준, 기준금리 25bp 인하", used)
    check("용어 풀이 붙음", "연준(미국의 중앙은행)" in s and "25bp(0.01%포인트, 25bp는 0.25%p)" in s, s)
    s2 = g.annotate("연준 또 인하, Fed 발표", used)
    check("같은 메시지에선 한 번만(별칭 포함)", "(" not in s2, s2)
    check("이미 괄호가 있으면 그대로", g.annotate("지캐시(ZEC) 급등") == "지캐시(ZEC) 급등")
    check("영문 단어 안은 안 건드림", g.annotate("ETFs and BP oil") == "ETFs and BP oil")
    check("긴 용어 우선", g.annotate("현물 ETF 승인").startswith("현물 ETF(실제 자산"), g.annotate("현물 ETF 승인"))
    check("호르무즈 해협 풀이", "세계 원유의 약 20%" in g.annotate("호르무즈 해협 봉쇄"))
    tg_all = "\n".join(msgs[-1]["telegram"])
    check("다이제스트 안에서 ETF 풀이 1회", tg_all.count("주식처럼 거래소에서 사고파는 펀드") == 1,
          tg_all.count("주식처럼 거래소에서 사고파는 펀드"))
    check("타이틀 이모지", msgs[0]["msg"]["header"].startswith("🚨") and msgs[-1]["msg"]["header"].startswith("📰"))
    check("텔레그램에 슬랙 문법 없음", "*<" not in tg_all and "|" not in tg_all.split("href")[0])


# --------------------------------- 이미지 ---------------------------------
def test_images():
    print("\n[이미지]")
    rss = b"""<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>A</title><link>https://c.test/a</link><media:content url="https://img.test/a.jpg" type="image/*" medium="image"/></item>
<item><title>B</title><link>https://c.test/b</link><enclosure url="https://img.test/b.jpg" type="image/jpeg" length="1"/></item>
<item><title>C</title><link>https://c.test/c</link><description>&lt;p&gt;&lt;img src="https://img.test/c.png"&gt;&lt;/p&gt;</description></item>
<item><title>D</title><link>https://c.test/d</link><media:thumbnail url="https://img.test/d.jpg"/></item>
<item><title>E</title><link>https://c.test/e</link><enclosure url="https://a.test/e.mp3" type="audio/mpeg"/></item>
</channel></rss>"""
    rows = {r["title"]: r["image"] for r in sources.parse_rss(rss, "t")}
    check("media:content 이미지", rows["A"] == "https://img.test/a.jpg", rows)
    check("enclosure 이미지", rows["B"] == "https://img.test/b.jpg", rows)
    check("본문 <img> 이미지", rows["C"] == "https://img.test/c.png", rows)
    check("media:thumbnail 이미지", rows["D"] == "https://img.test/d.jpg", rows)
    check("오디오 enclosure 는 무시", rows["E"] == "", rows)

    orig = sources._get
    try:
        def boom(*a, **k):
            raise AssertionError("요청하면 안 됨")
        sources._get = boom
        check("구글뉴스 링크는 og 요청 생략", sources.fetch_og_image("https://news.google.com/rss/articles/x") == "")

        class R:
            status_code, url = 200, "https://c.test/news/1"
            text = '<head><meta content="/img/cover.jpg" property="og:image"><meta name="x" content="y"></head>'
        sources._get = lambda *a, **k: R()
        check("og:image 파싱(속성 순서 무관·상대경로)", sources.fetch_og_image("https://c.test/news/1")
              == "https://c.test/img/cover.jpg")
        R.text = '<meta property="og:image" content="https://c.test/social-default-image.jpg">'
        check("사이트 기본 로고는 버림", sources.fetch_og_image("https://c.test/news/1") == "")

        def slow(*a, **k):
            raise TimeoutError("6초 초과")
        sources._get = slow
        check("시간초과면 빈값", sources.fetch_og_image("https://c.test/news/1") == "")
    finally:
        sources._get = orig

    its = _fake_items()[:3]
    its[0]["image"], its[2]["image"] = "", "https://img.test/third.jpg"
    msg = notify.compose(its, 85, "h", translate=lambda t: t)
    asked = []
    url, cap = notify.pick_photo(msg, fetch_og=lambda u: asked.append(u) or "https://img.test/og.jpg")
    check("가장 중요한 기사 og:image 1회만", url == "https://img.test/og.jpg" and asked == ["https://n.test/0"], asked)
    check("캡션은 짧은 제목", cap.count("\n") <= 1 and telegram_len(cap) <= 1024, cap)
    url2, _ = notify.pick_photo(msg, fetch_og=lambda u: "")
    check("og 없으면 다음 기사 RSS 이미지", url2 == "https://img.test/third.jpg", url2)
    px = notify.compose([dict(its[0], feed="price", image="")], 85, "h", translate=lambda t: t)
    check("시세 알림은 사진 없음", notify.pick_photo(px, fetch_og=lambda u: "https://x")[0] == "")


def telegram_len(s):
    from radar import telegram as tg
    return tg.tg_len(s)


# --------------------------------- 전송·seen ---------------------------------
def test_delivery_and_seen():
    print("\n[전송·seen]")
    from radar import runner, telegram as tg
    old_db = store.DB_PATH
    store.DB_PATH = os.path.join(tempfile.mkdtemp(), "d.db")
    o_slack, o_send, o_og = notify._send_slack, tg.send, sources.fetch_og_image
    sources.fetch_og_image = lambda u, timeout=6: ""
    cfg = dict(CFG, slack={"mode": "webhook", "webhook_url": "https://hook.invalid"})
    try:
        def run(slack_ok, tg_ok, env=True):
            sent = {"slack": 0, "tg": 0}

            def s(cfg_, msg):
                if not slack_ok:
                    raise RuntimeError("슬랙 다운")
                sent["slack"] += 1

            def t(msgs, photo=None, caption="", log=None, stream="NEWS"):
                if not tg_ok:
                    raise RuntimeError("텔레그램 다운")
                sent["tg"] += 1
                return len(msgs)
            notify._send_slack, tg.send = s, t
            its = _fake_items()[:2]
            new = [(store.norm_key(i["title"], i["url"]), i) for i in its]
            dropped = [(store.norm_key("접힌 기사 제목입니다 아주 길게", "u"), {})]
            res = runner._new_result("news", False, datetime.now(config.KST))
            kv = {"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "-1"} if env else {}
            with _Env(**kv):
                rep = notify.deliver(cfg, [i for _, i in new], log=lambda m: None)
            runner.apply_report(res, new, dropped, rep, log=lambda m: None)
            keys = [k for k, _ in new] + [k for k, _ in dropped]
            return res, store.is_new(keys), keys, sent

        res, fresh, keys, sent = run(True, False)
        check("텔레그램 실패해도 슬랙은 나감", sent["slack"] == 2 and res["sent"] == 2, (sent, res["sent"]))
        check("한쪽 성공이면 seen 등록(중복폭탄 방지)", fresh == set(), fresh)
        check("실패 채널은 channel_errors 로 남김", any(e.startswith("telegram") for e in res["channel_errors"])
              and res["error"] is None, res)

        store.DB_PATH = os.path.join(tempfile.mkdtemp(), "d2.db")
        res, fresh, keys, sent = run(False, True)
        check("슬랙 실패해도 텔레그램은 나감", sent["tg"] == 2 and fresh == set(), (sent, fresh))

        store.DB_PATH = os.path.join(tempfile.mkdtemp(), "d3.db")
        res, fresh, keys, sent = run(False, False)
        check("둘 다 실패면 seen 미등록(재시도)", fresh == set(keys) and res["sent"] == 0, (len(fresh), res["sent"]))
        check("둘 다 실패면 error", bool(res["error"]))

        store.DB_PATH = os.path.join(tempfile.mkdtemp(), "d4.db")
        res, fresh, keys, sent = run(True, True, env=False)
        check("텔레그램 변수 없으면 슬랙만", sent == {"slack": 2, "tg": 0} and res["channels"] == ["slack"], sent)

        notify._send_slack = o_slack
        try:
            with _Env():
                notify.deliver({"slack": {"mode": "webhook", "webhook_url": ""}}, _fake_items()[:1])
            check("경로가 하나도 없으면 예외", False)
        except RuntimeError:
            check("경로가 하나도 없으면 예외", True)
        with _Env(TELEGRAM_BOT_TOKEN_NEWS="T", TELEGRAM_CHAT_ID="-1"):
            check("텔레그램만 있어도 채널 성립", notify.channels({"slack": {"mode": "webhook", "webhook_url": ""}})
                  == ["telegram"])
    finally:
        notify._send_slack, tg.send, sources.fetch_og_image = o_slack, o_send, o_og
        store.DB_PATH = old_db


# --------------------------------- 미리보기 ---------------------------------
def test_preview():
    print("\n[미리보기]")
    from radar import runner
    old_db = store.DB_PATH
    store.DB_PATH = os.path.join(tempfile.mkdtemp(), "p.db")
    out_dir = Path(tempfile.mkdtemp())
    fake = [item("[속보] 이란 호르무즈 해협 전면 봉쇄"), item("비트코인 현물 ETF 자금 12억 달러 유입 급등")]
    fake[1]["image"] = "https://img.test/btc.jpg"
    orig = sources.collect
    sources.collect = lambda cfg, log=print: fake
    try:
        cfg = dict(CFG, price_watch=dict(CFG["price_watch"], enabled=False))
        with _Env():
            out = runner.preview(cfg, log=lambda m: None, out_dir=out_dir,
                                 fetch_og=lambda u: "", translate=lambda t: t)
        h = Path(out["html"]).read_text(encoding="utf-8")
        check("미리보기 파일 2종 생성", Path(out["html"]).exists() and Path(out["slack"]).exists())
        check("HTML 원문·분할·사진 URL 포함", "sendMessage" in h and "HTML 원문" in h and "img.test/btc.jpg" in h)
        check("미리보기는 seen 미등록", store.is_first_run() and len(store.is_new(
            [store.norm_key(i["title"], i["url"]) for i in fake])) == 2)
        store.mark_seen([store.norm_key(i["title"], i["url"]) for i in fake])
        with _Env():
            out2 = runner.preview(cfg, log=lambda m: None, out_dir=out_dir,
                                  fetch_og=lambda u: "", translate=lambda t: t)
        check("새 기사 없으면 이미 본 기사로 대체", out2["stats"]["ignored_seen"] and out2["stats"]["items"] == 2,
              out2["stats"])
    finally:
        sources.collect = orig
        store.DB_PATH = old_db


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
    test_telegram()
    test_tone_and_glossary()
    test_images()
    test_delivery_and_seen()
    test_preview()
    test_single_instance()
    if "--live" in sys.argv:
        test_live()
    print("\n%s\n결과: %d PASS / %d FAIL\n%s" % ("=" * 46, PASS, FAIL, "=" * 46))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
