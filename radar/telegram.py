# -*- coding: utf-8 -*-
"""텔레그램 전송 — 표준 라이브러리 + requests 만 쓴다.

환경변수(설정 파일엔 두지 않는다):
    TELEGRAM_BOT_TOKEN_NEWS  이 스트림(📰 세력의 정보원) 전용 봇 토큰. 없으면 ↓
    TELEGRAM_BOT_TOKEN       공용 봇 토큰(세력의 비서실장)
    TELEGRAM_CHAT_ID         슈퍼그룹 ID (-100…)
    TELEGRAM_TOPIC_NEWS      토픽(스레드) ID. 비우면 일반 대화방으로 간다

토큰이나 채팅 ID 가 없으면 enabled() 가 False 라서 조용히 건너뛴다.
"""
import html
import re
import time

import requests

API = "https://api.telegram.org/bot%s/%s"
MAX_TEXT = 4096
MAX_CAPTION = 1024
STREAM = "NEWS"

# 테스트에서 갈아끼울 수 있게 모듈 변수로 둔다
_post = requests.post
_sleep = time.sleep


# ─────────────────────────────────────────────────────────── 설정

def _env(key):
    import os
    return (os.environ.get(key) or "").strip()


def settings(stream=STREAM):
    """(token, chat_id, thread_id). 스트림 전용 토큰이 공용 토큰보다 우선한다."""
    token = _env("TELEGRAM_BOT_TOKEN_%s" % stream) or _env("TELEGRAM_BOT_TOKEN")
    return token, _env("TELEGRAM_CHAT_ID"), _env("TELEGRAM_TOPIC_%s" % stream)


def enabled(stream=STREAM):
    token, chat, _ = settings(stream)
    return bool(token and chat)


# ─────────────────────────────────────────────────────────── 텍스트 변환

def esc(s):
    """텔레그램 HTML 본문용 이스케이프(& < > 만)."""
    return html.escape(s or "", quote=False)


def esc_attr(s):
    return html.escape(s or "", quote=True)


# 슬랙 이모지 코드는 텔레그램에서 ":rotating_light:" 글자 그대로 보인다 → 유니코드로 바꾼다.
# 이 봇 코드는 유니코드 이모지를 직접 쓰지만(grep 결과 코드 0건), 4개 봇 공통 규격이라
# 형제 봇들에서 쓰는 코드까지 넉넉히 넣어둔다. 모르는 코드는 그대로 둔다.
EMOJI_MAP = {
    "rotating_light": "🚨", "warning": "⚠️", "pushpin": "📌", "round_pushpin": "📍",
    "point_right": "👉", "point_down": "👇", "bulb": "💡", "newspaper": "📰",
    "rolled_up_newspaper": "🗞️", "clock1": "🕐", "clock3": "🕒", "clock9": "🕘",
    "alarm_clock": "⏰", "hourglass": "⌛", "calendar": "📅", "date": "📅",
    "bank": "🏦", "oil_drum": "🛢️", "microphone": "🎤", "shield": "🛡️", "zap": "⚡",
    "coin": "🪙", "robot_face": "🤖", "chart_with_upwards_trend": "📈",
    "chart_with_downwards_trend": "📉", "bar_chart": "📊", "mag": "🔍", "mag_right": "🔎",
    "white_check_mark": "✅", "heavy_check_mark": "✔️", "x": "❌", "bangbang": "‼️",
    "exclamation": "❗", "fire": "🔥", "rocket": "🚀", "moneybag": "💰", "dollar": "💵",
    "money_with_wings": "💸", "gem": "💎", "star": "⭐", "sparkles": "✨", "bell": "🔔",
    "loudspeaker": "📢", "mega": "📣", "memo": "📝", "link": "🔗", "globe_with_meridians": "🌐",
    "earth_asia": "🌏", "us": "🇺🇸", "flag-us": "🇺🇸", "kr": "🇰🇷", "flag-kr": "🇰🇷",
    "large_green_circle": "🟢", "red_circle": "🔴", "large_yellow_circle": "🟡",
    "large_blue_circle": "🔵", "white_circle": "⚪", "black_circle": "⚫",
    "arrow_up": "⬆️", "arrow_down": "⬇️", "arrow_right": "➡️", "small_red_triangle": "🔺",
    "small_red_triangle_down": "🔻", "eyes": "👀", "thinking_face": "🤔", "tada": "🎉",
    "chart": "💹", "ballot_box_with_check": "☑️", "information_source": "ℹ️",
    "speech_balloon": "💬", "busts_in_silhouette": "👥", "crystal_ball": "🔮",
    "whale": "🐋", "bear": "🐻", "ox": "🐂", "scales": "⚖️", "hammer": "🔨",
    "lock": "🔒", "unlock": "🔓", "gear": "⚙️", "satellite_antenna": "📡",
    "thermometer": "🌡️", "compass": "🧭", "dart": "🎯", "trophy": "🏆", "medal": "🏅",
}

_EMOJI_CODE = re.compile(r":([a-z0-9_+\-]+):")


def emoji_codes_to_unicode(text):
    return _EMOJI_CODE.sub(lambda m: EMOJI_MAP.get(m.group(1), m.group(0)), text or "")


_SLACK_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]*))?>")


def slack_to_html(mrkdwn):
    """슬랙 mrkdwn → 텔레그램 HTML.

    `*굵게*`→<b>, `_기울임_`→<i>, `` `코드` ``→<code>, `<url|텍스트>`→<a href>,
    슬랙 엔티티(&lt; 등)는 먼저 풀고 텔레그램용으로 다시 이스케이프, 이모지 코드는 유니코드로.
    """
    text = emoji_codes_to_unicode(mrkdwn or "")
    links = []

    def _stash(m):
        url = html.unescape(m.group(1))
        label = html.unescape(m.group(2) if m.group(2) is not None else m.group(1))
        links.append((url, label))
        return "\x00%d\x00" % (len(links) - 1)

    text = _SLACK_LINK.sub(_stash, text)
    text = esc(html.unescape(text))

    codes = []

    def _code(m):
        codes.append(m.group(1))
        return "\x01%d\x01" % (len(codes) - 1)

    text = re.sub(r"`([^`\n]+)`", _code, text)  # 코드 안은 굵게/기울임 변환 금지
    text = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w_])_([^_\n]+?)_(?![\w_])", r"<i>\1</i>", text)
    text = re.sub(r"\x01(\d+)\x01", lambda m: "<code>%s</code>" % codes[int(m.group(1))], text)

    def _unstash(m):
        url, label = links[int(m.group(1))]
        return '<a href="%s">%s</a>' % (esc_attr(url), esc(label))

    return re.sub(r"\x00(\d+)\x00", _unstash, text)


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


# ─────────────────────────────────────────────────────────── 분할

def tg_len(s):
    """텔레그램은 UTF-16 코드 단위로 센다(이모지 1개 = 2). 태그까지 세서 보수적으로 잰다."""
    return len((s or "").encode("utf-16-le")) // 2


def _hard_split(block, limit):
    """한 줄이 통째로 limit 를 넘는 극단적 경우 — 태그를 걷어낸 평문으로 잘라 태그 중간 절단을 원천 차단."""
    plain = strip_tags(block)
    out, cur = [], ""
    for ch in plain:
        piece = esc(ch)
        if tg_len(cur) + tg_len(piece) > limit:
            out.append(cur)
            cur = ""
        cur += piece
    if cur:
        out.append(cur)
    return out


def split_html(blocks, limit=MAX_TEXT):
    """완결된 HTML 블록(기사 1건 등) 리스트를 limit 이하 메시지들로 묶는다.

    블록 사이는 빈 줄. 블록 하나가 limit 를 넘으면 줄 경계로, 줄 하나가 넘으면 평문으로 자른다.
    문자열 하나를 넘기면 빈 줄 경계로 블록을 나눠서 처리한다.
    """
    if isinstance(blocks, str):
        blocks = [b for b in re.split(r"\n\s*\n", blocks) if b.strip()]
    sep = "\n\n"
    units = []
    for b in blocks:
        if tg_len(b) <= limit:
            units.append(b)
            continue
        for line in b.split("\n"):
            units.extend([line] if tg_len(line) <= limit else _hard_split(line, limit))

    msgs, cur = [], ""
    for u in units:
        if not cur:
            cur = u
        elif tg_len(cur) + tg_len(sep) + tg_len(u) <= limit:
            cur += sep + u
        else:
            msgs.append(cur)
            cur = u
    if cur:
        msgs.append(cur)
    return msgs


def clip_caption(caption, limit=MAX_CAPTION):
    """사진 캡션(평문 기준으로 잘라 태그 깨짐 방지)."""
    if tg_len(caption) <= limit:
        return caption
    return _hard_split(caption, limit - 1)[0].rstrip() + "…"


# ─────────────────────────────────────────────────────────── 전송

def _call(token, method, payload, timeout=20):
    """429 면 retry_after 만큼 쉬고 1회 재시도. 실패는 예외."""
    url = API % (token, method)
    for attempt in (1, 2):
        r = _post(url, json=payload, timeout=timeout)
        try:
            js = r.json()
        except Exception:
            js = {}
        if r.status_code == 429 and attempt == 1:
            wait = ((js.get("parameters") or {}).get("retry_after")) or 3
            _sleep(min(float(wait), 60))
            continue
        if r.status_code == 200 and js.get("ok"):
            return js
        # 토큰이 에러 메시지에 섞여 로그로 새지 않게 설명만 남긴다
        raise RuntimeError("텔레그램 %s 실패 %s %s"
                           % (method, r.status_code, str(js.get("description") or r.text)[:200]))
    raise RuntimeError("텔레그램 %s 실패 (429 재시도 후에도 제한)" % method)


def _base(chat, thread):
    p = {"chat_id": chat}
    if thread:
        try:
            p["message_thread_id"] = int(thread)
        except ValueError:
            pass
    return p


def send_message(text, stream=STREAM):
    token, chat, thread = settings(stream)
    payload = dict(_base(chat, thread), text=text, parse_mode="HTML",
                   disable_web_page_preview=True)
    return _call(token, "sendMessage", payload)


def send_photo(photo_url, caption="", stream=STREAM, timeout=15):
    token, chat, thread = settings(stream)
    payload = dict(_base(chat, thread), photo=photo_url, parse_mode="HTML",
                   caption=clip_caption(caption))
    return _call(token, "sendPhoto", payload, timeout=timeout)


def send(messages, photo=None, caption="", stream=STREAM, log=print):
    """사진(있으면, 실패 무시) → 본문 메시지들(사이 1초). 본문이 하나라도 실패하면 예외."""
    if photo:
        try:
            send_photo(photo, caption, stream=stream)
            _sleep(1)
        except Exception as e:  # 사진은 덤이다. 본문은 무조건 보낸다
            log("  텔레그램 사진 생략: %s" % e)
    for n, m in enumerate(messages):
        if n:
            _sleep(1)
        send_message(m, stream=stream)
    return len(messages)
