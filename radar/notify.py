# -*- coding: utf-8 -*-
"""알림 조립 + 전송 — 슬랙(웹훅 / 크롬 폴백)과 텔레그램에 같은 내용을 보낸다.

흐름: compose(번역·용어풀이 1회) → render_slack / render_telegram → deliver.
말투는 전부 합니다체("~입니다", "~하기 때문입니다"). 해요체 어미가 남으면 테스트가 잡는다.
"""
import json
import re
from datetime import datetime, timezone, timedelta

import requests

from radar import glossary, telegram

KST = timezone(timedelta(hours=9))
BOT_NAME = "세력의 비서실장"

TOPIC_EMOJI = {
    "금리·통화정책": "🏦",
    "호르무즈·지정학": "🛢️",
    "트럼프·주요인사 발언": "🎤",
    "비트코인": "₿",
    "지캐시(ZEC)": "🛡️",
    "하이퍼리퀴드(HYPE)": "⚡",
    "코인 전반·규제": "🪙",
    "AI": "🤖",
    "가격 급변": "📈",
    "코인 급등락 스캔": "🔎",
}


# 제목만 던지면 "그래서 나랑 무슨 상관?"이 안 보인다 — 주제별로 왜 중요한지 한 줄
WHY_LABEL = "💡 중요한 이유:"
TOPIC_WHY = {
    "금리·통화정책": "금리가 바뀌면 달러·주식·코인 가격이 한꺼번에 흔들리기 때문입니다.",
    "호르무즈·지정학": "호르무즈 해협이 막히거나 긴장이 커지면 유가가 뛰고, 주식·코인 같은 위험자산이 약해지기 쉽기 때문입니다.",
    "트럼프·주요인사 발언": "말 한마디로 관세나 시장 분위기가 곧바로 바뀔 수 있기 때문입니다.",
    "비트코인": "비트코인의 방향이 코인 시장 전체의 분위기를 좌우하기 때문입니다.",
    "지캐시(ZEC)": "관심 종목으로 지켜보고 계신 지캐시 소식이라, 가격에 바로 영향을 줄 수 있기 때문입니다.",
    "하이퍼리퀴드(HYPE)": "관심 종목으로 지켜보고 계신 하이퍼리퀴드 소식이라, 가격에 바로 영향을 줄 수 있기 때문입니다.",
    "코인 전반·규제": "규제 소식은 코인 가격에 크고 빠르게 반영되기 때문입니다.",
    "AI": "AI 관련주와 반도체 테마의 흐름에 영향을 줄 수 있기 때문입니다.",
    "가격 급변": "짧은 시간에 가격이 크게 움직였기 때문입니다. 원인이 된 뉴스를 함께 확인해 보시는 것이 좋아 보입니다.",
    "코인 급등락 스캔": "시장 전체에서 유독 크게 움직인 코인이라 이유를 살펴볼 만하기 때문입니다.",
}
INTRO_URGENT = "방금 들어온 중요한 뉴스라 바로 알려드립니다."
INTRO_DIGEST = "지난 알림 이후 들어온 뉴스 중 챙겨 보실 만한 것만 골랐습니다. 제목을 누르시면 기사로 이동합니다."
FOOTER = "뉴스 레이더 · %s 기준 · 중요도는 주제·키워드·출처를 바탕으로 매긴 점수입니다."

_HANGUL = re.compile(r"[가-힣]")


def _ko(text):
    """영어 제목 → 한국어 (구글 공개 번역, 키 불필요). 실패하면 원문 그대로."""
    if not text or _HANGUL.search(text):
        return text
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single",
                         params={"client": "gtx", "sl": "auto", "tl": "ko", "dt": "t", "q": text[:500]},
                         timeout=10)
        return "".join(seg[0] for seg in r.json()[0] if seg and seg[0]).strip() or text
    except Exception:
        return text


def _tier(score, urgent_score):
    if score >= urgent_score:
        return "🚨", "긴급"
    if score >= urgent_score - 15:
        return "⚠️", "중요"
    return "📌", "참고"


def batches_of(items, urgent_score):
    """긴급건은 한 건씩 따로, 나머지는 한 방에 묶어 다이제스트로."""
    urgent = [i for i in items if i["score"] >= urgent_score]
    rest = [i for i in items if i["score"] < urgent_score]
    out = [([u], "🚨 긴급 뉴스 — %s" % u.get("topic", "")) for u in urgent]
    if rest:
        out.append((rest, "📰 챙겨 보실 뉴스 %d건" % len(rest)))
    return out


# ─────────────────────────────────────────────────────────── 조립(채널 공통)

def compose(items, urgent_score, header, translate=_ko, now=None):
    """번역과 용어 풀이는 여기서 한 번만 한다 — 슬랙과 텔레그램이 같은 문장을 받는다."""
    used = set()  # 한 메시지 안에서 같은 용어는 한 번만 풀이
    arts = []
    for it in items:
        ko = translate(it["title"]) or it["title"]
        topic = it.get("topic", "")
        why = TOPIC_WHY.get(topic, "")
        emoji, tier = _tier(it["score"], urgent_score)
        pub = it.get("published")
        arts.append({
            "tier_emoji": emoji, "tier": tier,
            "topic": topic, "topic_emoji": TOPIC_EMOJI.get(topic, "•"),
            "title": glossary.annotate(ko, used),
            "title_plain": ko,
            "original": it["title"][:120] if ko != it["title"] else "",
            "why": glossary.annotate(why, used) if why else "",
            "url": it.get("url", ""),
            "when": pub.astimezone(KST).strftime("%m월 %d일 %H:%M") if pub else "",
            "source": it.get("source", ""),
            "score": int(it["score"]),
            "image": it.get("image", "") or "",
            "feed": it.get("feed", ""),
        })
    single_urgent = len(items) == 1 and items[0]["score"] >= urgent_score
    stamp = (now or datetime.now(KST)).strftime("%m월 %d일 %H:%M")
    return {"header": header, "intro": INTRO_URGENT if single_urgent else INTRO_DIGEST,
            "articles": arts, "footer": FOOTER % stamp}


def _meta(a):
    meta = [a["when"]] if a["when"] else []
    if a["source"]:
        meta.append("출처 %s" % a["source"])
    meta.append("중요도 %d점" % a["score"])
    return " · ".join(meta)


# ─────────────────────────────────────────────────────────── 슬랙

def _sesc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_section(a):
    head = "%s *%s* · %s %s" % (a["tier_emoji"], a["tier"], a["topic_emoji"], a["topic"])
    title = _sesc(a["title"])
    body = "*<%s|%s>*" % (a["url"], title) if a["url"] else "*%s*" % title
    lines = [head, body]
    if a["original"]:
        lines.append("_원제: %s_" % _sesc(a["original"]))
    if a["why"]:
        lines.append("%s %s" % (WHY_LABEL, _sesc(a["why"])))
    lines.append(_meta(a))
    return "\n".join(lines)


def render_slack(msg):
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": msg["header"], "emoji": True}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": "_%s_" % msg["intro"]}]}]
    for a in msg["articles"]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": slack_section(a)}})
        blocks.append({"type": "divider"})
    if blocks[-1]["type"] == "divider":
        blocks.pop()
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": msg["footer"]}]})
    return blocks


def slack_plain(msg):
    """알림 미리보기·크롬 폴백용 평문."""
    out = [msg["header"]]
    for a in msg["articles"]:
        out.append("%s [%s|%s] %s %s" % (a["tier_emoji"], a["tier"], a["topic"], a["title_plain"], a["url"]))
    return "\n".join(out)


def slack_preview_text(msg):
    """블록을 사람이 읽는 순서대로 이어붙인 mrkdwn (미리보기 파일용)."""
    parts = ["*%s*" % msg["header"], "_%s_" % msg["intro"]]
    parts += [slack_section(a) for a in msg["articles"]]
    parts.append(msg["footer"])
    return "\n\n".join(parts)


def _line(item, urgent_score):
    """기사 1건의 슬랙 mrkdwn (하위 호환)."""
    return slack_section(compose([item], urgent_score, "")["articles"][0])


def build_blocks(items, urgent_score, title_text):
    """하위 호환: 아이템 → 슬랙 블록."""
    return render_slack(compose(items, urgent_score, title_text))


def send_webhook(url, text, blocks):
    payload = {"text": text, "blocks": blocks}
    r = requests.post(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, timeout=20)
    if r.status_code != 200 or r.text.strip() != "ok":
        raise RuntimeError("슬랙 웹훅 실패 %s %s" % (r.status_code, r.text[:200]))


def send_playwright(cfg, text):
    """웹훅 없이 로그인된 크롬(CDP)의 슬랙 웹에 직접 입력."""
    from radar import slack_cdp
    pw_cfg = cfg["slack"].get("playwright", {})
    channel_url = pw_cfg.get("channel_url")
    if not channel_url:
        raise RuntimeError("config.json 의 slack.playwright.channel_url 이 비어 있음")
    slack_cdp.post(channel_url, text, cdp=pw_cfg.get("cdp", "http://127.0.0.1:9222"))


def backend_of(cfg):
    """실제로 어떤 경로로 나갈지 — webhook / playwright / none."""
    mode = cfg["slack"].get("mode", "webhook")
    if mode == "webhook" and (cfg["slack"].get("webhook_url") or "").strip():
        return "webhook"
    if (cfg["slack"].get("playwright", {}).get("channel_url") or "").strip():
        return "playwright"
    return "none"


def _send_slack(cfg, msg):
    b = backend_of(cfg)
    if b == "webhook":
        send_webhook(cfg["slack"]["webhook_url"].strip(), slack_plain(msg), render_slack(msg))
    elif b == "playwright":
        send_playwright(cfg, slack_plain(msg))
    else:
        raise RuntimeError("슬랙 경로 없음")


# ─────────────────────────────────────────────────────────── 텔레그램

def telegram_blocks(msg):
    """기사 1건 = 완결된 HTML 블록 1개. 분할은 이 블록 경계에서만 일어난다."""
    e = telegram.esc
    blocks = ["<b>%s</b>\n<i>%s</i>" % (e(msg["header"]), e(msg["intro"]))]
    for a in msg["articles"]:
        lines = ["%s <b>%s</b> · %s %s" % (a["tier_emoji"], e(a["tier"]), a["topic_emoji"], e(a["topic"]))]
        title = e(a["title"])
        lines.append('<b><a href="%s">%s</a></b>' % (telegram.esc_attr(a["url"]), title)
                     if a["url"] else "<b>%s</b>" % title)
        if a["original"]:
            lines.append("<i>원제: %s</i>" % e(a["original"]))
        if a["why"]:
            lines.append("%s %s" % (WHY_LABEL, e(a["why"])))
        lines.append(e(_meta(a)))
        blocks.append("\n".join(lines))
    blocks.append("<i>%s · %s</i>" % (BOT_NAME, e(msg["footer"])))
    return blocks


def render_telegram(msg):
    return telegram.split_html(telegram_blocks(msg))


# 가격 알림(바이낸스 거래 페이지)·거래소 공지는 기사 사진이 없다
_NO_PHOTO_FEEDS = ("price", "binance", "upbit")


def pick_photo(msg, fetch_og=None):
    """메시지당 사진 최대 1장. 중요도 순으로 RSS 이미지가 있는 기사를 찾고,
    가장 중요한 기사에 RSS 이미지가 없으면 그 기사 원문 og:image 를 1회만 시도한다.
    돌려주는 값: (사진 URL, 캡션 HTML) 또는 ("", "")."""
    arts = sorted(msg["articles"], key=lambda a: -a["score"])
    arts = [a for a in arts if a["feed"] not in _NO_PHOTO_FEEDS]
    if not arts:
        return "", ""
    chosen, url = None, ""
    top = arts[0]
    if top["image"]:
        chosen, url = top, top["image"]
    elif fetch_og and top["url"]:
        url = fetch_og(top["url"]) or ""
        chosen = top if url else None
    if not url:
        for a in arts[1:]:
            if a["image"]:
                chosen, url = a, a["image"]
                break
    if not url:
        return "", ""
    cap = "%s <b>%s</b>" % (chosen["tier_emoji"], telegram.esc(chosen["title_plain"][:200]))
    if chosen["source"]:
        cap += "\n%s · 출처 %s" % (telegram.esc(chosen["topic"]), telegram.esc(chosen["source"]))
    return url, telegram.clip_caption(cap)


# ─────────────────────────────────────────────────────────── 출고

def render_batches(cfg, items, with_photo=True, fetch_og=None, translate=_ko):
    """실제 전송과 미리보기가 똑같은 결과물을 쓰도록 여기서 한 번에 만든다."""
    if fetch_og is None and with_photo:
        from radar.sources import fetch_og_image as fetch_og
    urgent_score = cfg.get("urgent_score", 85)
    out = []
    for batch, header in batches_of(items, urgent_score):
        msg = compose(batch, urgent_score, header, translate=translate)
        photo, caption = pick_photo(msg, fetch_og) if with_photo else ("", "")
        out.append({"items": batch, "msg": msg, "slack_blocks": render_slack(msg),
                    "slack_text": slack_preview_text(msg), "telegram": render_telegram(msg),
                    "photo": photo, "caption": caption})
    return out


def channels(cfg):
    ch = []
    if backend_of(cfg) != "none":
        ch.append("slack")
    if telegram.enabled():
        ch.append("telegram")
    return ch


def deliver(cfg, items, log=print):
    """모든 채널로 보낸다. 한 채널 실패가 다른 채널을 막지 않는다.

    반환: {"sent_items": 한 채널이라도 성공한 아이템, "failed_items": 모든 채널이 실패한 아이템,
           "channel_errors": ["telegram: ..."], "channels": [...]}
    전송 경로가 하나도 없으면 예외(→ runner 가 seen 미등록 처리).
    """
    report = {"sent_items": [], "failed_items": [], "channel_errors": [], "channels": channels(cfg)}
    if not items:
        return report
    if not report["channels"]:
        raise RuntimeError("전송 경로가 없습니다. SLACK_WEBHOOK_URL 또는 TELEGRAM_BOT_TOKEN(_NEWS)+"
                           "TELEGRAM_CHAT_ID 를 설정해야 합니다.")
    tg_on = "telegram" in report["channels"]
    for b in render_batches(cfg, items, with_photo=tg_on):
        ok = False
        if "slack" in report["channels"]:
            try:
                _send_slack(cfg, b["msg"])
                ok = True
            except Exception as e:
                report["channel_errors"].append("slack: %s" % e)
                log("  슬랙 전송 실패: %s" % e)
        if tg_on:
            try:
                telegram.send(b["telegram"], photo=b["photo"], caption=b["caption"], log=log)
                ok = True
            except Exception as e:
                report["channel_errors"].append("telegram: %s" % e)
                log("  텔레그램 전송 실패: %s" % e)
        (report["sent_items"] if ok else report["failed_items"]).extend(b["items"])
    return report


def ping(cfg):
    """연결 테스트 메시지 1발(설정된 모든 채널). 성공한 경로 이름 목록을 돌려준다."""
    stamp = datetime.now(KST).strftime("%m/%d %H:%M")
    text = "✅ 뉴스 레이더 연결 테스트입니다. 이 메시지가 보이면 알림 경로가 정상입니다."
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text":
               "✅ *뉴스 레이더 연결 테스트*\n이 메시지가 보이면 알림 경로가 정상입니다."}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": "%s KST" % stamp}]}]
    done, errors = [], []
    b = backend_of(cfg)
    try:
        if b == "webhook":
            send_webhook((cfg["slack"].get("webhook_url") or "").strip(), text, blocks)
            done.append("webhook")
        elif b == "playwright":
            send_playwright(cfg, text)
            done.append("playwright")
    except Exception as e:
        errors.append("slack: %s" % e)
    if telegram.enabled():
        try:
            telegram.send_message(telegram.slack_to_html(
                "✅ *뉴스 레이더 연결 테스트*\n이 메시지가 보이면 알림 경로가 정상입니다.\n_%s KST · %s_"
                % (stamp, BOT_NAME)))
            done.append("telegram")
        except Exception as e:
            errors.append("telegram: %s" % e)
    if not done:
        raise RuntimeError(" / ".join(errors) or
                           "알림 경로가 없습니다. .env 의 SLACK_WEBHOOK_URL 또는 TELEGRAM_BOT_TOKEN+"
                           "TELEGRAM_CHAT_ID 를 채워야 합니다.")
    return ",".join(done)
