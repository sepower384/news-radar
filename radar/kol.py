# -*- coding: utf-8 -*-
"""💼 세력 수익 레이더 — KOL(인플루언서)용 정보 코너. 하루 한 번.

강회장 수익 구조(거래소·프로젝트 레퍼럴, 멤버십, 유튜브·텔레그램 채널) 기준으로
"소개해서 돈이 되는 것"과 "그 돈을 위협하는 것"만 모은다.

  1) 🤝 실제로 돈을 버는 프로젝트 — DefiLlama 수수료 수익(키 불필요). 수익이 있어야 레퍼럴도 오래 준다.
     레퍼럴 운영 이력은 손으로 확인한 곳만 표시하고, 나머지는 '확인 필요'로 둔다(조건·요율은 적지 않는다).
  2) 👀 급성장(아직 검증 전) — 수익이 한 달 새 크게 는 곳. 먼저 써 보고 소개할 후보.
  3) 🆕 새 레퍼럴·KOL 프로그램 소식 / 🪂 포인트·에어드랍(콘텐츠 소재) / ⚖️ 수익에 영향 주는 규제·플랫폼 소식
  꼬리: 소개 전 체크 3줄(광고 표기·미신고 해외 서비스·수익 보장 금지).
"""
from datetime import datetime, timedelta, timezone

import requests

from radar import cluster, notify, sources, store, telegram

KST = timezone(timedelta(hours=9))
FEES_URL = "https://api.llama.fi/overview/fees"
TITLE = "💼 세력 수익 레이더 — KOL용 정보"

# DefiLlama 분류 → (한글 이름, 소개할 때 꼭 붙일 주의)
CATEGORIES = {
    "Derivatives": ("선물 거래소", "레버리지 상품이라 청산 위험 안내가 꼭 필요합니다."),
    "Telegram Bot": ("텔레그램 매매봇", "밈코인 매매 도구라 손실 위험 안내가 꼭 필요합니다."),
    "Trading App": ("매매 앱", "밈코인 매매 도구라 손실 위험 안내가 꼭 필요합니다."),
    "Launchpad": ("코인 발행 플랫폼", "새로 찍어내는 밈코인은 대부분 가치가 사라져, 소개에 특히 주의가 필요합니다."),
    "Prediction Market": ("예측시장", "한국 접속 차단·도박 규제 문제가 있어 국내 구독자 대상 소개는 맞지 않습니다."),
    "DEX Aggregator": ("거래 중개", "스왑 도구라 위험은 낮은 편이지만 사기 토큰 주의 안내가 필요합니다."),
    "Dexs": ("탈중앙 거래소", "스왑 도구라 위험은 낮은 편이지만 사기 토큰 주의 안내가 필요합니다."),
    "Wallets": ("지갑", "지갑 복구 문구 관리 안내가 필요합니다."),
}

# 레퍼럴(추천 보상) 운영 이력을 확인한 곳만 — 요율·조건은 수시로 바뀌므로 적지 않는다.
REFERRAL_KNOWN = {
    "hyperliquid": "추천 코드로 들어온 사람의 거래 수수료 일부를 돌려받는 구조를 운영해 왔습니다.",
    "gmgn": "초대 링크 기반 수수료 리워드를 운영해 왔습니다.",
    "axiom": "추천 링크 기반 수수료 리워드를 운영해 왔습니다.",
    "photon": "추천 링크 기반 수수료 리워드를 운영해 왔습니다.",
    "bullx": "추천 링크 기반 수수료 리워드를 운영해 왔습니다.",
    "trojan": "추천 링크 기반 수수료 리워드를 운영해 왔습니다.",
    "banana-gun": "추천 링크 기반 수수료 리워드를 운영해 왔습니다.",
    "maestro": "추천 링크 기반 수수료 리워드를 운영해 왔습니다.",
    "pump.fun": "추천 리워드를 운영한 이력이 있습니다.",
    "gmx": "추천 코드 등급제(수수료 할인·리베이트)를 운영해 왔습니다.",
    "aster": "추천 코드 수수료 리베이트를 운영해 왔습니다.",
    "drift": "추천 코드 수수료 공유를 운영해 왔습니다.",
    "dydx": "제휴(어필리에이트) 프로그램을 운영해 왔습니다.",
}

NEWS_SECTIONS = [
    {
        "title": "🆕 새 레퍼럴·KOL 프로그램 소식",
        "queries": [('crypto "referral program" when:3d', "en"), ('crypto "affiliate program" when:3d', "en"),
                    ('crypto "ambassador program" when:3d', "en"), ('"creator program" crypto when:3d', "en"),
                    ('"partner program" crypto when:3d', "en"), ("코인 레퍼럴 when:3d", "ko"),
                    ("앰배서더 프로그램 코인 when:3d", "ko")],
        "must": ("referral", "affiliate", "ambassador", "creator", "kol", "partner program", "cashback", "rebate",
                 "레퍼럴", "리퍼럴", "앰배서더", "추천인", "페이백", "파트너"),
        "crypto_only": True,
    },
    {
        "title": "🪂 포인트·에어드랍 (콘텐츠 소재)",
        "queries": [('crypto "points program" when:3d', "en"), ("airdrop season crypto when:3d", "en"),
                    ("에어드랍 코인 when:3d", "ko")],
        "must": ("points", "airdrop", "에어드랍", "에어드롭", "포인트"),
    },
    {
        "title": "⚖️ 내 수익에 영향 주는 규제·플랫폼 소식",
        "queries": [("유사투자자문 when:7d", "ko"), ("리딩방 when:7d", "ko"), ("핀플루언서 when:7d", "ko"),
                    ("가상자산 광고 규제 when:7d", "ko"), ("해외 가상자산거래소 영업 when:7d", "ko"),
                    ("유튜브 수익 정책 when:7d", "ko"), ("finfluencer regulation when:7d", "en")],
        "must": ("유사투자", "리딩방", "핀플루언서", "광고", "미신고", "해외 거래소", "해외거래소", "우회 영업",
                 "유튜브", "유튜버", "finfluencer", "promotion"),
    },
]
# 도박 스팸·추천코드 광고글·사전판매 홍보는 버린다
SPAM = ("카지노", "룰렛", "포커", "슬롯", "토토", "바카라", "도박", "promo code", "referral code", "bonus code",
        "invite code", "초대 코드", "초대코드", "추천 코드", "presale", "pre-sale", "sign up bonus", "가입 보너스",
        "price prediction", "sponsored", "$50 bonus", "보너스 코드")
SPAM_SOURCES = ("histoire pour tous", "sportsbook wire", "covers.com")
CRYPTO_WORDS = ("crypto", "coin", "token", "bitcoin", "ethereum", "solana", "defi", "web3", "blockchain", "exchange",
                "dex", "wallet", "hedera", "코인", "가상자산", "암호화폐", "거래소", "토큰", "블록체인")

CHECKLIST = [
    "소개글에는 '광고·제휴 링크'임을 먼저 밝히셔야 합니다(표시광고법 뒷광고 금지).",
    "국내에 신고되지 않은 해외 거래소·서비스를 국내 구독자에게 권하는 것은 특금법 위반 소지가 있습니다.",
    "'수익 보장'·'원금 보장' 같은 표현은 쓰지 않는 것이 안전하고, 손실 위험 안내를 함께 붙이시는 것이 좋습니다.",
]


# ─────────────────────────────────────────────────────────── 1·2) 돈 버는 프로젝트

def fetch_fees(get=requests.get):
    r = get(FEES_URL, params={"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true",
                              "dataType": "dailyRevenue"}, timeout=40)
    return r.json().get("protocols", [])


def _ref_note(slug):
    s = (slug or "").lower()
    for k, v in REFERRAL_KNOWN.items():
        if s == k or s.startswith(k + "-") or s.startswith(k + "."):
            return v
    return ""


def pick_projects(protocols, n_top=6, n_rising=3):
    """(검증된 수익 상위, 급성장 후보)."""
    rows = []
    for p in protocols:
        cat = p.get("category")
        if cat not in CATEGORIES:
            continue
        m30 = p.get("total30d") or 0
        prev = p.get("total60dto30d") or 0
        if m30 < 1e6:
            continue
        rows.append({
            "name": p.get("displayName") or p.get("name"), "slug": p.get("slug") or "",
            "category": cat, "rev30": m30, "prev30": prev, "growth": p.get("change_1m"),
            "referral": _ref_note(p.get("slug")),
        })
    # 같은 회사의 여러 상품(Hyperliquid Perps/Spot)은 수익 큰 것 하나만
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: -r["rev30"]):
        base = r["slug"].split("-")[0].split(".")[0]
        if base in seen:
            continue
        seen.add(base)
        uniq.append(r)
    proven = [r for r in uniq if r["prev30"] >= 5e5]
    proven.sort(key=lambda r: (not r["referral"], r["category"] == "Prediction Market", -r["rev30"]))
    top = proven[:n_top]
    taken = {r["slug"] for r in top}
    cands = [r for r in uniq if r["slug"] not in taken and (r["growth"] or 0) >= 80
             and r["category"] != "Prediction Market"]
    cands.sort(key=lambda r: -(r["growth"] or 0))
    # 한 분류가 목록을 다 차지하지 않게(밈코인 발행 플랫폼 3연속 방지) 분류당 1개씩 먼저
    rising, cats = [], set()
    for r in cands:
        if r["category"] not in cats:
            rising.append(r)
            cats.add(r["category"])
    rising += [r for r in cands if r not in rising]
    return top, rising[:n_rising]


def _money(v):
    return "$%.1fM" % (v / 1e6) if v < 1e9 else "$%.2fB" % (v / 1e9)


def project_lines(r, rising=False):
    kr, caution = CATEGORIES[r["category"]]
    link = "https://defillama.com/protocol/%s" % r["slug"]
    g = r.get("growth")
    grow = "" if g is None else " · 전월 대비 %+.0f%%" % g
    head = '<b><a href="%s">%s</a></b> · %s · 30일 수익 %s%s' % (
        telegram.esc_attr(link), telegram.esc(r["name"]), kr, _money(r["rev30"]), grow)
    lines = [head]
    if r["referral"]:
        lines.append("🤝 " + telegram.esc(r["referral"]) + " 조건은 공식 페이지에서 확인하시는 것이 좋습니다.")
    else:
        lines.append("🔍 레퍼럴 운영 여부는 아직 확인되지 않았습니다.")
    if rising and r["prev30"] < 5e5:
        lines.append("🆕 수익이 생긴 지 한 달 남짓이라, 직접 써 보고 소개하시는 것이 안전합니다.")
    lines.append("⚠️ " + telegram.esc(caution))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────── 3) 뉴스

def _clean(items, must, crypto_only=False):
    out = []
    for it in items:
        t = (it.get("title") or "")
        tl = t.lower()
        if any(w in tl for w in SPAM) or (it.get("source") or "").lower() in SPAM_SOURCES:
            continue
        if not any(w in tl for w in must):
            continue
        if crypto_only and not any(w in tl for w in CRYPTO_WORDS):
            continue
        out.append(it)
    return out


def gather_news(fetch=sources.google_news, translate=notify._ko, per_section=3, max_age_days=7):
    now = datetime.now(timezone.utc)
    out = []
    for sec in NEWS_SECTIONS:
        pool = []
        for q, lang in sec["queries"]:
            try:
                pool += fetch(q, lang)
            except Exception:
                continue
        pool = [i for i in _clean(pool, sec["must"], sec.get("crypto_only"))
                if not i.get("published") or now - i["published"] <= timedelta(days=max_age_days)]
        pool.sort(key=lambda i: i.get("published") or now, reverse=True)
        for i in pool[:30]:
            i["title_ko"] = translate(i["title"]) or i["title"]
        groups = cluster.group(pool[:30])
        picked = []
        for rep, dupes in groups:
            k = store.norm_key("kol|" + rep["title"], rep.get("url", ""))
            if not store.is_new([k]):
                continue
            rep["_key"] = k
            rep["_more"] = len(dupes)
            picked.append(rep)
            if len(picked) >= per_section:
                break
        out.append((sec["title"], picked))
    return out


def news_line(i):
    e = telegram.esc
    when = ""
    if i.get("published"):
        when = i["published"].astimezone(KST).strftime("%m/%d")
    meta = " · ".join(x for x in (i.get("source"), when) if x)
    more = " · 비슷한 기사 %d건 더" % i["_more"] if i.get("_more") else ""
    return '• <a href="%s">%s</a> <i>(%s%s)</i>' % (
        telegram.esc_attr(i.get("url", "")), e(i.get("title_ko") or i["title"]), e(meta), e(more))


# ─────────────────────────────────────────────────────────── 조립·발송

def build(top, rising, news, now=None):
    now = now or datetime.now(KST)
    e = telegram.esc
    blocks = ["<b>%s</b>\n<i>%s · 소개해서 돈이 되는 것과, 그 돈을 위협하는 것만 모았습니다.</i>"
              % (e(TITLE), now.strftime("%m월 %d일"))]
    if top:
        blocks.append("<b>🤝 실제로 돈을 버는 프로젝트</b>\n<i>수수료 수익이 있어야 레퍼럴도 오래 줍니다. "
                      "30일 수익은 DefiLlama 집계입니다.</i>")
        blocks += [project_lines(r) for r in top]
    if rising:
        blocks.append("<b>👀 급성장 — 아직 검증 전</b>")
        blocks += [project_lines(r, rising=True) for r in rising]
    for title, items in news:
        if items:
            blocks.append("<b>%s</b>\n%s" % (e(title), "\n".join(news_line(i) for i in items)))
    blocks.append("<b>✅ 소개 전 체크</b>\n" + "\n".join("• " + e(c) for c in CHECKLIST))
    blocks.append("<i>%s · 정보 제공용이며 특정 프로젝트 가입·투자 권유가 아닙니다.</i>" % e(notify.BOT_NAME))
    return blocks


def collect(translate=notify._ko, fetch_fees_fn=fetch_fees, fetch_news=sources.google_news, log=print):
    top, rising = [], []
    try:
        top, rising = pick_projects(fetch_fees_fn())
    except Exception as ex:
        log("  [KOL] DefiLlama 실패: %s" % ex)
    news = gather_news(fetch=fetch_news, translate=translate)
    return top, rising, news


def due(cfg, now):
    conf = cfg.get("kol_corner", {})
    if not conf.get("enabled", True):
        return False
    if now.hour < conf.get("hour_kst", 10):
        return False
    return store.get_state("kol_last") != now.strftime("%Y-%m-%d")


def send(cfg, blocks, log=print):
    """텔레그램 우선, 슬랙 웹훅이 있으면 같이. 하나라도 성공하면 True."""
    ok = False
    if telegram.enabled():
        try:
            telegram.send(telegram.split_html(blocks), log=log)
            ok = True
        except Exception as ex:
            log("  [KOL] 텔레그램 실패: %s" % ex)
    if notify.backend_of(cfg) == "webhook":
        try:
            text = telegram.strip_tags("\n\n".join(blocks))
            notify.send_webhook(cfg["slack"]["webhook_url"].strip(), text[:2900],
                                [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}])
            ok = True
        except Exception as ex:
            log("  [KOL] 슬랙 실패: %s" % ex)
    return ok


def maybe_send(cfg, now=None, force=False, log=print, **kw):
    now = now or datetime.now(KST)
    if not force and not due(cfg, now):
        return False
    top, rising, news = collect(log=log, **kw)
    if not top and not any(items for _, items in news):
        log("  [KOL] 보낼 내용 없음")
        return False
    if not send(cfg, build(top, rising, news, now), log=log):
        return False
    store.set_state("kol_last", now.strftime("%Y-%m-%d"))
    store.mark_seen([i["_key"] for _, items in news for i in items])
    log("  [KOL] 수익 레이더 발송 (프로젝트 %d + 급성장 %d + 소식 %d)"
        % (len(top), len(rising), sum(len(x) for _, x in news)))
    return True


def preview_html(blocks):
    body = "\n".join('<div class="tg">%s</div>' % c for c in telegram.split_html(blocks))
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>KOL 코너 미리보기</title>"
            "<style>body{font-family:system-ui,'Malgun Gothic',sans-serif;background:#0e1621;color:#e8eef4;"
            "padding:16px}.tg{background:#182533;border-radius:10px;padding:10px 12px;white-space:pre-wrap;"
            "line-height:1.5;max-width:720px;margin:8px auto}.tg a{color:#6ab3f3}</style></head><body>%s"
            "</body></html>" % body)
