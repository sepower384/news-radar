# -*- coding: utf-8 -*-
"""설정 로딩 — config.json + .env. 외부 의존성 없음."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"
KST = timezone(timedelta(hours=9))


def _load_env():
    """.env / .env.local 을 os.environ 에 반영(기존 값은 안 덮어씀)."""
    for name in (".env", ".env.local"):
        p = ROOT / name
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


_load_env()


def env(key, default=""):
    return (os.environ.get(key) or default).strip()


def load_config(path=None):
    """config.json 을 읽고 환경변수로 비밀값을 덮어쓴다."""
    p = Path(path) if path else CONFIG_PATH
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg.setdefault("slack", {})
    env_hook = env("SLACK_WEBHOOK_NEWS") or env("SLACK_WEBHOOK_URL")
    if not (cfg["slack"].get("webhook_url") or "").strip():
        cfg["slack"]["webhook_url"] = env_hook
    # 환경변수로 웹훅이 들어왔으면(=GitHub Actions 등 클라우드) config 의 mode 와 무관하게 웹훅.
    # 클라우드엔 로그인된 크롬이 없어서 playwright 모드면 웹훅이 있어도 전송이 실패한다.
    if env_hook:
        cfg["slack"]["mode"] = "webhook"
    ch = env("SLACK_NEWS_CHANNEL_URL")
    if ch:
        cfg["slack"].setdefault("playwright", {})["channel_url"] = ch
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return cfg


def in_quiet_hours(cfg, now=None):
    """조용시간(KST 정시 기준). 이 시간엔 긴급건만 나간다."""
    hours = cfg.get("quiet_hours") or []
    if not hours:
        return False
    now = now or datetime.now(KST)
    return now.astimezone(KST).hour in set(hours)
