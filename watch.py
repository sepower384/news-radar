# -*- coding: utf-8 -*-
"""상시 감시 루프. pythonw.exe 로 띄우면 콘솔 창 없이 백그라운드로 돈다.

    pythonw.exe watch.py

- 뉴스 사이클: config.json 의 interval_sec 마다 (기본 15분)
- 시세 사이클: price_interval_sec 마다 (기본 5분, 뉴스보다 촘촘하게)
"""
import os
import sys
import time
import traceback
from datetime import datetime

os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from radar import runner  # noqa: E402
from radar.config import DATA_DIR, KST, load_config  # noqa: E402

LOG = DATA_DIR / "watch.log"
LOCK = DATA_DIR / "watch.lock"
MAX_LOG_BYTES = 2 * 1024 * 1024
_lock_fh = None


def acquire_single_instance():
    """이미 돌고 있으면 False. 프로세스가 죽으면 잠금도 같이 풀린다.

    예약작업의 30분 트리거는 vbs가 즉시 끝나버려서 MultipleInstances 설정이 안 먹는다.
    그대로 두면 30분마다 감시 루프가 한 개씩 늘어난다 — 그걸 여기서 막는다.
    """
    global _lock_fh
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(LOCK, "a+")
    except OSError:
        return True  # 잠금을 못 만들면 막지 않는다(감시가 멈추는 쪽이 더 나쁘다)
    try:
        try:
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _lock_fh = fh  # 프로세스가 살아있는 동안 열어둔다
    return True


def log(msg):
    line = "[%s] %s" % (datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:
            LOG.rename(LOG.with_suffix(".log.1"))
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass  # pythonw 에는 stdout 이 없다


def main():
    if not acquire_single_instance():
        log("이미 돌고 있어 중복 실행을 건너뜀 (pid=%s)" % os.getpid())
        return
    cfg = load_config()
    interval = int(cfg.get("interval_sec", 900))
    px_interval = int(cfg.get("price_interval_sec", 300))
    log("뉴스 레이더 시작 (뉴스 %ds / 시세 %ds, pid=%s)" % (interval, px_interval, os.getpid()))

    last_news = 0.0
    while True:
        try:
            cfg = load_config()  # 설정을 고쳐도 재시작 없이 반영
            now = time.time()
            mode = "all" if now - last_news >= interval else "price"
            if mode == "all":
                last_news = now
            res = runner.cycle(mode, log=lambda m: None, cfg=cfg)
            for err in res.get("channel_errors") or []:
                log("%s 사이클 일부 채널 실패: %s" % (mode, err))
            if res.get("error"):
                log("%s 사이클 전송실패: %s" % (mode, res["error"]))
            elif res["sent"]:
                log("%s 사이클 → 전송 %d건 (뉴스후보 %d, 시세 %d)"
                    % (mode, res["sent"], res["news_candidates"], res["price_alerts"]))
            elif res.get("first_run"):
                log("첫 실행 학습 완료 — 다음 턴부터 알립니다")
        except KeyboardInterrupt:
            log("사용자 중지")
            return
        except Exception:
            log("사이클 예외:\n" + traceback.format_exc())
        time.sleep(px_interval)


if __name__ == "__main__":
    main()
