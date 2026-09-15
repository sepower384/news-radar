# -*- coding: utf-8 -*-
"""무료 소스 수집기 — API 키 0개. RSS는 표준 라이브러리로 파싱(feedparser 불필요)."""
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"}
TIMEOUT = 20


def _get(url, **kw):
    """윈도우 SSL 인증서 이슈 대비: 실패 시 1회 verify=False 재시도."""
    kw.setdefault("headers", HEADERS)
    kw.setdefault("timeout", TIMEOUT)
    try:
        return requests.get(url, **kw)
    except requests.exceptions.SSLError:
        import urllib3
        urllib3.disable_warnings()
        kw["verify"] = False
        return requests.get(url, **kw)


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def _strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"&nbsp;?", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&[a-z#0-9]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
            try:
                d = datetime.strptime(s.strip(), fmt)
                break
            except Exception:
                d = None
        if d is None:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


MRSS = "{http://search.yahoo.com/mrss/}"
ATOM = "{http://www.w3.org/2005/Atom}"
_IMG_SRC = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)


def _is_img_url(u):
    return bool(u) and u.startswith(("http://", "https://"))


def rss_image(it, desc_raw=""):
    """RSS 아이템의 대표 이미지. media:content → media:thumbnail → enclosure → 본문 <img> 순.

    실측(2026-09-15): 코인데스크·코인텔레그래프·더블록은 media:content 100%, 연준·구글뉴스는 0%.
    """
    thumb = ""
    for el in it.iter():
        tag = el.tag
        url = (el.get("url") or el.get("href") or "").strip()
        if not _is_img_url(url):
            continue
        typ, medium = (el.get("type") or "").lower(), (el.get("medium") or "").lower()
        if tag == MRSS + "content":
            if medium == "image" or typ.startswith("image") or (not typ and not medium):
                return url
        elif tag == MRSS + "thumbnail":
            thumb = thumb or url
        elif tag == "enclosure" or (tag == ATOM + "link" and el.get("rel") == "enclosure"):
            if typ.startswith("image"):
                thumb = thumb or url
    if thumb:
        return thumb
    m = _IMG_SRC.search(desc_raw or "")
    return m.group(1) if m and _is_img_url(m.group(1)) else ""


def parse_rss(xml_bytes, source_name):
    """RSS 2.0 / Atom 모두 처리."""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    atom = ATOM
    nodes = root.findall(".//item") or root.findall(".//" + atom + "entry")
    for it in nodes:
        title = _text(it.find("title")) or _text(it.find(atom + "title"))
        link = _text(it.find("link"))
        if not link:
            le = it.find(atom + "link")
            link = le.get("href", "") if le is not None else ""
        desc = _text(it.find("description")) or _text(it.find(atom + "summary"))
        pub = _text(it.find("pubDate")) or _text(it.find("published")) or _text(it.find(atom + "updated"))
        src_el = it.find("source")
        publisher = _text(src_el) or source_name
        if not title:
            continue
        out.append({
            "title": _strip_html(title),
            "url": link,
            "summary": _strip_html(desc)[:400],
            "published": _parse_date(pub),
            "source": publisher,
            "feed": source_name,
            "image": rss_image(it, desc),
        })
    return out


# ---------------------------------------------------------------- 기사 대표 이미지(og:image)

# 구글뉴스 기사 링크는 JS 리다이렉트 페이지라 og:image 가 없다(실측 9/9 없음) → 요청 자체를 안 한다.
# 바이낸스 시세/공지 페이지는 봇 차단(202)·로고뿐이라 역시 생략.
OG_SKIP_HOSTS = ("news.google.com", "binance.com", "upbit.com")
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*["']([^"']*)["']""")
# 사이트 공용 기본 이미지(연준 social-default, 업비트 facebook 로고 등)는 기사 사진이 아니다
_GENERIC_IMG = re.compile(r"default|logo|favicon|placeholder|facebook\.png|/seo/", re.I)


def fetch_og_image(url, timeout=6):
    """기사 원문의 og:image / twitter:image. 실패·시간초과·기본로고면 ''."""
    host = urllib.parse.urlparse(url or "").netloc.lower()
    if not host or any(host == h or host.endswith("." + h) for h in OG_SKIP_HOSTS):
        return ""
    try:
        r = _get(url, timeout=timeout)
        if r.status_code != 200:
            return ""
        page = r.text[:400000]
    except Exception:
        return ""
    found = {}
    for tag in _META.findall(page):
        attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image") and attrs.get("content"):
            found.setdefault(key, attrs["content"].strip())
    for key in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image"):
        img = found.get(key)
        if not img:
            continue
        img = urllib.parse.urljoin(r.url or url, img)
        if _is_img_url(img) and not _GENERIC_IMG.search(img):
            return img
    return ""


def _fresh(items, hours):
    if not hours:
        return items
    cut = datetime.now(timezone.utc).timestamp() - hours * 3600
    keep = []
    for i in items:
        p = i.get("published")
        if p is None or p.timestamp() >= cut:
            keep.append(i)
    return keep


# ---------------------------------------------------------------- 개별 소스

def google_news(query, lang="ko"):
    if lang == "ko":
        url = ("https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko"
               % urllib.parse.quote(query))
    else:
        url = ("https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
               % urllib.parse.quote(query))
    r = _get(url)
    if r.status_code != 200:
        return []
    items = parse_rss(r.content, "구글뉴스")
    for i in items:
        # 구글뉴스 제목은 "본문 - 매체명" 형태
        if " - " in i["title"]:
            head, _, tail = i["title"].rpartition(" - ")
            if head and len(tail) < 40:
                i["title"], i["source"] = head, tail
    return items


def simple_rss(url, name):
    r = _get(url)
    if r.status_code != 200:
        return []
    return parse_rss(r.content, name)


def binance_announcements():
    """바이낸스 공지 — 상장/상장폐지/입출금 중단이 여기서 제일 먼저 뜬다."""
    url = ("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
           "?type=1&catalogId=48&pageNo=1&pageSize=20")
    try:
        r = _get(url, headers={**HEADERS, "Accept": "application/json"})
        js = r.json()
    except Exception:
        return []
    arts = []
    data = js.get("data") or {}
    for cat in (data.get("catalogs") or []):
        arts.extend(cat.get("articles") or [])
    arts.extend(data.get("articles") or [])
    out = []
    for a in arts:
        code = a.get("code") or ""
        ts = a.get("releaseDate")
        out.append({
            "title": a.get("title", ""),
            "url": "https://www.binance.com/en/support/announcement/%s" % code,
            "summary": "",
            "published": datetime.fromtimestamp(ts / 1000, timezone.utc) if ts else None,
            "source": "바이낸스 공지",
            "feed": "binance",
        })
    return [o for o in out if o["title"]]


def upbit_notices():
    url = ("https://api-manager.upbit.com/api/v1/announcements"
           "?os=web&page=1&per_page=20&category=all")
    try:
        r = _get(url, headers={**HEADERS, "Accept": "application/json",
                               "Referer": "https://upbit.com/service_center/notice"})
        js = r.json()
    except Exception:
        return []
    notices = ((js.get("data") or {}).get("notices")) or js.get("data") or []
    out = []
    for n in notices if isinstance(notices, list) else []:
        nid = n.get("id")
        out.append({
            "title": n.get("title", ""),
            "url": "https://upbit.com/service_center/notice?id=%s" % nid,
            "summary": "",
            "published": _parse_date(n.get("listed_at") or n.get("created_at")),
            "source": "업비트 공지",
            "feed": "upbit",
        })
    return [o for o in out if o["title"]]


# ---------------------------------------------------------------- 가격 급변

# api.binance.com 은 미국 IP 를 451 로 막는다 → GitHub Actions(미국 서버)에선 0건.
# data-api.binance.vision 은 바이낸스 공식 공개시세 미러라 지역 차단이 없다.
BINANCE_TICKER_URLS = (
    "https://api.binance.com/api/v3/ticker/24hr",
    "https://data-api.binance.vision/api/v3/ticker/24hr",
)


def binance_tickers(symbols):
    rows = None
    for url in BINANCE_TICKER_URLS:
        try:
            r = _get(url)
            js = r.json() if r.status_code == 200 else None
        except Exception:
            js = None
        if isinstance(js, list) and js:
            rows = js
            break
    if rows is None:
        return {}, []
    wanted = {s.upper() for s in symbols}
    picked, allrows = {}, []
    for row in rows:
        sym = row.get("symbol", "")
        try:
            entry = {
                "symbol": sym,
                "price": float(row.get("lastPrice", 0) or 0),
                "pct24h": float(row.get("priceChangePercent", 0) or 0),
                "quote_vol": float(row.get("quoteVolume", 0) or 0),
            }
        except (TypeError, ValueError):
            continue
        if sym in wanted:
            picked[sym] = entry
        if sym.endswith("USDT"):
            allrows.append(entry)
    return picked, allrows


# ---------------------------------------------------------------- 통합 수집

RSS_FEEDS = {
    "fed": ("https://www.federalreserve.gov/feeds/press_all.xml", "연준(Fed) 공식"),
    "coindesk": ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
    "cointelegraph": ("https://cointelegraph.com/rss", "Cointelegraph"),
    "theblock": ("https://www.theblock.co/rss.xml", "The Block"),
}


def collect(cfg, log=print):
    """설정에 걸린 모든 소스를 긁어 뉴스 아이템 리스트로 반환."""
    items, seen_urls = [], set()
    hours = cfg.get("lookback_hours", 6)
    srcs = cfg.get("sources", {})

    def add(batch, label):
        n = 0
        for i in _fresh(batch, hours):
            u = i.get("url") or i.get("title")
            if u in seen_urls:
                continue
            seen_urls.add(u)
            items.append(i)
            n += 1
        log("  [%s] %d건" % (label, n))

    if srcs.get("google_news", True):
        for topic, t in cfg.get("topics", {}).items():
            for q in t.get("queries", []):
                lang = "ko" if re.search(r"[가-힣]", q) else "en"
                try:
                    add(google_news(q, lang), "구글뉴스:%s" % q)
                except Exception as e:
                    log("  [구글뉴스:%s] 실패 %s" % (q, e))
                time.sleep(0.4)

    for key, (url, name) in RSS_FEEDS.items():
        if not srcs.get(key, True):
            continue
        try:
            add(simple_rss(url, name), name)
        except Exception as e:
            log("  [%s] 실패 %s" % (name, e))

    if srcs.get("binance_announcements", True):
        try:
            add(binance_announcements(), "바이낸스 공지")
        except Exception as e:
            log("  [바이낸스 공지] 실패 %s" % e)

    if srcs.get("upbit_notices", True):
        try:
            add(upbit_notices(), "업비트 공지")
        except Exception as e:
            log("  [업비트 공지] 실패 %s" % e)

    return items
