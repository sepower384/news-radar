# -*- coding: utf-8 -*-
"""같은 사건 묶기 — 매체·언어가 달라도 한 사건은 한 번만 보낸다.

한국어 헤드라인은 단어 단위 자카드가 0.1대라 안 먹힌다(2026-09-12 실측).
그래서 **번역된 한국어 제목의 글자 2-gram** 겹침(Dice)과 **고유명사·숫자 앵커** 공유를 같이 본다.

    same_event("업비트 상장 JPYC 190%대 급등", "업비트서 스테이블코인 상장 직후 190%대 급등") -> True
"""
import re

_MEDIA_TAIL = re.compile(r"\s[-|–]\s[^-|–]{1,30}$")
_TAG = re.compile(r"^\s*(?:[\[\(<【（][^\]\)>】）]{0,12}[\]\)>】）]\s*)+")
_WORD = re.compile(r"[0-9a-z가-힣]+")

# 어느 기사에나 나오는 말은 앵커가 못 된다
STOP = {
    "코인", "가상자산", "암호화폐", "비트코인", "시장", "가격", "급등", "급락", "상승", "하락", "미국", "한국",
    "발표", "속보", "단독", "종합", "기자", "뉴스", "오늘", "이번", "관련", "위해", "대한", "통해", "있다", "없다",
    "했다", "한다", "달러", "억원", "만에", "이후", "the", "and", "for", "with", "crypto", "bitcoin", "price",
}


def normalize(title):
    t = _TAG.sub("", title or "")
    t = _MEDIA_TAIL.sub("", t)
    return t.lower()


SEP = "‖"  # "번역제목‖원제" — 글자 겹침은 번역제목으로, 주체·사건은 둘 다에서 찾는다


def bigrams(title):
    out = set()
    for w in _WORD.findall(normalize(title.split(SEP)[0])):
        if len(w) == 1:
            continue
        out.update(w[i:i + 2] for i in range(len(w) - 1))
    return out


def anchors(title):
    """고유명사·숫자 후보: 조사 떼기 대신 앞 2~4글자 줄기로 비교한다."""
    out = set()
    for w in _WORD.findall(normalize(title)):
        if w in STOP or len(w) < 2:
            continue
        if w.isdigit():
            if len(w) >= 2:
                out.add("#" + w)
            continue
        stem = w[:4] if re.match(r"[a-z]", w) else w[:3]
        if stem not in STOP:
            out.add(stem)
    return out


def dice(a, b):
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


# 주체(누가/무엇이) — 별칭은 한 이름으로 모은다
ENTITIES = {
    "FED": ("연준", "fed", "fomc", "파월", "powell", "美", "미국", "미 ", "미,"),
    "UK": ("영국", "英", "영란은행", "boe"),
    "BOK": ("한은", "한국은행", "금통위"),
    "ECB": ("ecb", "유럽중앙은행"),
    "BOJ": ("일본은행", "boj", "日銀"),
    "BTC": ("비트코인", "bitcoin", "btc"),
    "ETH": ("이더리움", "ethereum", "eth"),
    "ZEC": ("지캐시", "zcash", "zec"),
    "HYPE": ("하이퍼리퀴드", "hyperliquid", "hype"),
    "XRP": ("리플", "ripple", "xrp"),
    "SOL": ("솔라나", "solana", "sol"),
    "UPBIT": ("업비트", "upbit"),
    "BINANCE": ("바이낸스", "binance"),
    "COINBASE": ("코인베이스", "coinbase"),
    "TRUMP": ("트럼프", "trump"),
    "IRAN": ("이란", "iran", "호르무즈", "hormuz"),
    "NVDA": ("엔비디아", "nvidia"),
    "OPENAI": ("openai", "오픈ai", "챗gpt", "chatgpt"),
    "ANTHROPIC": ("anthropic", "앤트로픽", "claude"),
    "CLARITY": ("클래리티", "clarity"),
}
# 사건 종류
EVENTS = {
    "HIKE": ("금리 인상", "금리인상", "rate hike", "인상 결정", "기준금리 인상", "긴축"),
    "CUT": ("금리 인하", "금리인하", "rate cut", "인하 결정"),
    "HOLD": ("동결", "hold rates", "holds rates"),
    "UP": ("급등", "폭등", "껑충", "surge", "jump", "soar", "rall", "최고치", "최고 기록", "신고가", "record high"),
    "DOWN": ("급락", "폭락", "plunge", "crash", "tumble", "sink", "최저"),
    "LIST": ("상장", "listing", "lists "),
    "DELIST": ("상장폐지", "delist", "거래지원 종료"),
    "HACK": ("해킹", "hack", "exploit", "탈취", "drain"),
    "ETF": ("etf",),
    "TARIFF": ("관세", "tariff"),
    "BILL": ("법안", "bill", " act", "부결", "통과"),
}
_LATIN = re.compile(r"^[a-z]+$")


def _has(text, word):
    if _LATIN.match(word) and len(word) <= 5:
        return re.search(r"(?<![a-z])%s" % re.escape(word), text) is not None
    return word in text


def tags(title, table):
    t = " ".join(normalize(x) for x in title.split(SEP))
    return {k for k, words in table.items() if any(_has(t, w) for w in words)}


# 배경으로 자주 곁들여지는 주체 — "금리 인상 속 지캐시 급등"의 주인공은 지캐시다
GENERIC = {"FED", "BTC"}


def _same_subject(e1, e2):
    s1, s2 = e1 - GENERIC, e2 - GENERIC
    if s1 or s2:
        return bool(s1 & s2)
    return e1 == e2


def same_event(t1, t2, threshold=0.45):
    # '상장'과 '상장폐지'는 글자가 거의 같아도 정반대 사건
    if ("DELIST" in tags(t1, EVENTS)) != ("DELIST" in tags(t2, EVENTS)):
        return False
    b1, b2 = bigrams(t1), bigrams(t2)
    d = dice(b1, b2)
    if d >= threshold:
        return True
    # 같은 주체 + 같은 사건 종류 = 같은 이야기 (지캐시 급등을 다섯 매체가 쓴 경우)
    ev = tags(t1, EVENTS) & tags(t2, EVENTS)
    e1, e2 = tags(t1, ENTITIES), tags(t2, ENTITIES)
    if ev and e1 and e2 and _same_subject(e1, e2):
        return True
    shared = anchors(t1.split(SEP)[0]) & anchors(t2.split(SEP)[0])
    # 앵커 3개 이상 공유 + 글자 겹침도 어느 정도면 같은 사건
    return len(shared) >= 3 and d >= 0.2


def key_of(item):
    ko, raw = item.get("title_ko") or "", item.get("title", "")
    return ko + SEP + raw if ko and ko != raw else raw


def group(items, key=key_of):
    """점수순 목록 → [대표, [같은 사건 다른 기사...]] 목록. 대표는 각 묶음의 첫(최고점) 기사."""
    groups = []
    for it in items:
        t = key(it)
        for g in groups:
            if same_event(key(g[0]), t):
                g[1].append(it)
                break
        else:
            groups.append([it, []])
    return groups


def seen_recently(title, recent_titles):
    return any(same_event(title, r) for r in recent_titles)
