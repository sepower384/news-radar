# -*- coding: utf-8 -*-
"""한 번만 돌고 종료.

    python run_once.py            # 뉴스 + 시세 전부
    python run_once.py news       # 뉴스만
    python run_once.py price      # 코인 급등락만
    python run_once.py dry        # 수집·채점만 하고 전송/기록 없음 (안전 미리보기)
    python run_once.py test       # 슬랙 연결 테스트 1발
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
        print("전송 성공 (백엔드: %s)" % b)
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
    return 1 if res.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
