# -*- coding: utf-8 -*-
"""한 번만 돌고 종료.

    python run_once.py                    # 뉴스 + 시세 전부
    python run_once.py news               # 뉴스만
    python run_once.py price              # 코인 급등락만
    python run_once.py dry                # 수집·채점만 하고 전송/기록 없음 (안전 미리보기)
    python run_once.py preview-telegram   # 실제 데이터로 슬랙·텔레그램 메시지를 파일로만 저장
    python run_once.py test               # 슬랙·텔레그램 연결 테스트 1발
"""
import json
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from radar import notify, runner  # noqa: E402
from radar.config import load_config  # noqa: E402


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    cfg = load_config()

    if arg == "test":
        try:
            b = notify.ping(cfg)
        except Exception as e:
            print("전송 실패: %s" % e)
            return 1
        print("전송 성공 (경로: %s)" % b)
        return 0

    if arg in ("preview-telegram", "preview"):
        out = runner.preview(cfg)
        print("\n" + "=" * 60)
        print("텔레그램 미리보기: %s" % out["html"])
        print("슬랙 미리보기   : %s" % out["slack"])
        print(json.dumps(out["stats"], ensure_ascii=False, indent=2))
        return 0

    dry = arg in ("dry", "--dry", "dry-run")
    mode = arg if arg in ("news", "price") else "all"
    res = runner.cycle(mode, dry=dry, cfg=cfg)

    print("\n" + "=" * 60)
    for i in res["items"]:
        print(" %3d  [%s] %s" % (i["score"], i["topic"], i["title"][:70]))
    print("=" * 60)
    print(json.dumps({k: v for k, v in res.items() if k != "items"},
                     ensure_ascii=False, indent=2))
    # 한쪽 채널만 실패하면 알림은 나간 것이라 성공(0)으로 끝내되, Actions 화면에 경고를 띄운다
    if os.environ.get("GITHUB_ACTIONS") and res.get("channel_errors") and not res.get("error"):
        for err in res["channel_errors"]:
            print("::warning::일부 채널 전송 실패 — %s" % err[:300])
    return 1 if res.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
