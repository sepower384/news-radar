# -*- coding: utf-8 -*-
"""슬랙 전송 — 기본은 Incoming Webhook, 없으면 로그인된 크롬 + Playwright 폴백."""
import json
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


def _tier(score, urgent_score):
    if score >= urgent_score:
        return "🚨", "긴급"
    if score >= urgent_score - 15:
        return "⚠️", "중요"
    return "📌", "참고"


def _line(item, urgent_score):
    emoji, tier = _tier(item["score"], urgent_score)
    topic = TOPIC_EMOJI.get(item.get("topic", ""), "•")
    title = item["title"].replace("<", "&lt;").replace(">", "&gt;")
    url = item.get("url", "")
    head = "%s *%s* %s `%s` _%s_" % (emoji, tier, topic, item.get("topic", ""), item.get("source", ""))
    body = "<%s|%s>" % (url, title) if url else title
    pub = item.get("published")
    when = pub.astimezone(KST).strftime("%m/%d %H:%M") if pub else ""
    meta = "score %d" % item["score"] + (" · %s KST" % when if when else "")
    return "%s\n%s\n_%s_" % (head, body, meta)


def build_blocks(items, urgent_score, title_text):
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": title_text, "emoji": True}}]
    for it in items:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _line(it, urgent_score)}})
        blocks.append({"type": "divider"})
    if blocks and blocks[-1]["type"] == "divider":
        blocks.pop()
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": "뉴스 레이더 · %s KST" % datetime.now(KST).strftime("%m/%d %H:%M")}]})
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
    from playwright.sync_api import sync_playwright
    pw_cfg = cfg["slack"]["playwright"]
    channel_url = pw_cfg.get("channel_url")
    if not channel_url:
        raise RuntimeError("config.json 의 slack.playwright.channel_url 이 비어 있음")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(pw_cfg.get("cdp", "http://127.0.0.1:9222"))
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = None
        for pg in ctx.pages:
            if "slack.com" in (pg.url or ""):
                page = pg
                break
        if page is None:
            page = ctx.new_page()
        page.goto(channel_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        box = page.locator('div[data-qa="message_input"] div[contenteditable="true"]').first
        box.wait_for(state="visible", timeout=30000)
        box.click()
        for i, line in enumerate(text.split("\n")):
            if i:
                page.keyboard.press("Shift+Enter")
            page.keyboard.insert_text(line)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)


def deliver(cfg, items, log=print):
    """긴급건은 개별 메시지, 나머지는 한 방에 묶어 다이제스트로."""
    if not items:
        return 0
    urgent_score = cfg.get("urgent_score", 85)
    mode = cfg["slack"].get("mode", "webhook")
    webhook = (cfg["slack"].get("webhook_url") or "").strip()

    urgent = [i for i in items if i["score"] >= urgent_score]
    rest = [i for i in items if i["score"] < urgent_score]

    batches = [([u], "🚨 긴급 — %s" % u.get("topic", "")) for u in urgent]
    if rest:
        batches.append((rest, "⚠️ 주요 이슈 %d건" % len(rest)))

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
