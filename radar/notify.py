# -*- coding: utf-8 -*-
"""슬랙 전송 — 기본은 Incoming Webhook, 없으면 로그인된 크롬 + Playwright 폴백."""
import json
import re
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))

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
TOPIC_WHY = {
    "금리·통화정책": "금리가 바뀌면 달러·주식·코인 가격이 한꺼번에 흔들려요",
    "호르무즈·지정학": "세계 원유가 지나는 길이라 긴장되면 유가가 뛰고 주식·코인 같은 위험자산이 약해져요",
    "트럼프·주요인사 발언": "말 한마디로 관세나 시장 분위기가 바로 바뀔 수 있어요",
    "비트코인": "비트코인 방향이 코인 시장 전체 분위기를 좌우해요",
    "지캐시(ZEC)": "지켜보는 코인(지캐시) 관련 소식이에요",
    "하이퍼리퀴드(HYPE)": "지켜보는 코인(하이퍼리퀴드) 관련 소식이에요",
    "코인 전반·규제": "규제 소식은 코인 가격에 크게, 그리고 빠르게 반영돼요",
    "AI": "AI 관련주·테마 흐름에 영향을 줄 수 있어요",
    "가격 급변": "짧은 시간에 가격이 크게 움직였어요 — 원인 뉴스를 같이 확인해보세요",
    "코인 급등락 스캔": "시장에서 유독 크게 움직인 코인이에요",
}
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


def _line(item, urgent_score):
    emoji, tier = _tier(item["score"], urgent_score)
    topic_name = item.get("topic", "")
    topic = TOPIC_EMOJI.get(topic_name, "•")
    ko = _ko(item["title"])
    title = ko.replace("<", "&lt;").replace(">", "&gt;")
    url = item.get("url", "")
    head = "%s *%s* · %s %s" % (emoji, tier, topic, topic_name)
    body = "*<%s|%s>*" % (url, title) if url else "*%s*" % title
    lines = [head, body]
    if ko != item["title"]:
        lines.append("_원제: %s_" % item["title"][:120].replace("<", "&lt;").replace(">", "&gt;"))
    why = TOPIC_WHY.get(topic_name)
    if why:
        lines.append("👉 왜 중요해요? %s" % why)
    pub = item.get("published")
    when = pub.astimezone(KST).strftime("%m월 %d일 %H:%M") if pub else ""
    meta = ["🕒 %s" % when] if when else []
    if item.get("source"):
        meta.append("출처 %s" % item["source"])
    meta.append("중요도 %d점" % item["score"])
    lines.append(" · ".join(meta))
    return "\n".join(lines)


def build_blocks(items, urgent_score, title_text):
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": title_text, "emoji": True}}]
    intro = ("_방금 들어온 중요한 뉴스라 바로 알려드려요._" if len(items) == 1 and items[0]["score"] >= urgent_score
             else "_지난 알림 이후 들어온 뉴스 중 챙겨볼 만한 것만 골랐어요. 제목을 누르면 기사로 가요._")
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": intro}]})
    for it in items:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _line(it, urgent_score)}})
        blocks.append({"type": "divider"})
    if blocks and blocks[-1]["type"] == "divider":
        blocks.pop()
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": "뉴스 레이더 · %s 기준 · 중요도는 주제·키워드·출처로 매긴 점수예요"
         % datetime.now(KST).strftime("%m월 %d일 %H:%M")}]})
    return blocks


def send_webhook(url, text, blocks):
    payload = {"text": text, "blocks": blocks}
    r = requests.post(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, timeout=20)
    if r.status_code != 200 or r.text.strip() != "ok":
        raise RuntimeError("슬랙 웹훅 실패 %s %s" % (r.status_code, r.text[:200]))


def _plain(items, urgent_score, title_text):
    out = [title_text]
    for it in items:
        emoji, tier = _tier(it["score"], urgent_score)
        out.append("%s [%s|%s] %s %s" % (emoji, tier, it.get("topic", ""), it["title"], it.get("url", "")))
    return "\n".join(out)


def send_playwright(cfg, text):
    """웹훅 없이 로그인된 크롬(CDP)의 슬랙 웹에 직접 입력."""
    from radar import slack_cdp
    pw_cfg = cfg["slack"].get("playwright", {})
    channel_url = pw_cfg.get("channel_url")
    if not channel_url:
        raise RuntimeError("config.json 의 slack.playwright.channel_url 이 비어 있음")
    slack_cdp.post(channel_url, text, cdp=pw_cfg.get("cdp", "http://127.0.0.1:9222"))


def deliver(cfg, items, log=print):
    """긴급건은 개별 메시지, 나머지는 한 방에 묶어 다이제스트로."""
    if not items:
        return 0
    urgent_score = cfg.get("urgent_score", 85)
    mode = cfg["slack"].get("mode", "webhook")
    webhook = (cfg["slack"].get("webhook_url") or "").strip()

    urgent = [i for i in items if i["score"] >= urgent_score]
    rest = [i for i in items if i["score"] < urgent_score]

    batches = [([u], "🚨 긴급 뉴스 — %s" % u.get("topic", "")) for u in urgent]
    if rest:
        batches.append((rest, "📰 챙겨볼 뉴스 %d건" % len(rest)))

    sent = 0
    for batch, header in batches:
        text = _plain(batch, urgent_score, header)
        blocks = build_blocks(batch, urgent_score, header)
        try:
            if mode == "webhook" and webhook:
                send_webhook(webhook, text, blocks)
            else:
                send_playwright(cfg, text)
            sent += len(batch)
        except Exception as e:
            log("  전송 실패: %s" % e)
            raise
    return sent


def backend_of(cfg):
    """실제로 어떤 경로로 나갈지 — webhook / playwright / none."""
    mode = cfg["slack"].get("mode", "webhook")
    if mode == "webhook" and (cfg["slack"].get("webhook_url") or "").strip():
        return "webhook"
    if (cfg["slack"].get("playwright", {}).get("channel_url") or "").strip():
        return "playwright"
    return "none"


def ping(cfg):
    """연결 테스트 메시지 1발. 성공하면 사용한 백엔드 이름을 돌려준다."""
    text = "✅ 뉴스 레이더 연결 테스트 — 이 메시지가 보이면 알림 경로 정상입니다."
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text":
               "✅ *뉴스 레이더 연결 테스트*\n이 메시지가 보이면 알림 경로 정상입니다."}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text":
               "%s KST" % datetime.now(KST).strftime("%m/%d %H:%M")}]}]
    b = backend_of(cfg)
    if b == "webhook":
        send_webhook((cfg["slack"].get("webhook_url") or "").strip(), text, blocks)
    elif b == "playwright":
        send_playwright(cfg, text)
    else:
        raise RuntimeError("슬랙 경로가 없습니다. .env 의 SLACK_WEBHOOK_URL 또는 "
                           "config.json 의 slack.playwright.channel_url 을 채워주세요.")
    return b
