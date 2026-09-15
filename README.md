# 뉴스 레이더 (news-radar)

토픽별 뉴스를 점수로 걸러 **큰 것만** 슬랙으로 쏜다. 코인 급등락 감시는 덤.
**API 키 0개 · 요금 0원** (구글뉴스 RSS · 연준 RSS · 코인데스크/코인텔레그래프/더블록 · 바이낸스/업비트 공지 · 바이낸스 공개시세).

```
python run_once.py dry     # ← 여기부터. 전송·기록 없이 "뭐가 걸리는지"만 본다
```

---

## 1. 5분 세팅

```powershell
cd C:\dev\news-radar
pip install -r requirements.txt          # requests 하나뿐
copy .env.example .env                   # SLACK_WEBHOOK_URL 한 줄만 채우면 끝
python run_once.py test                  # 슬랙에 테스트 메시지 1발
python run_once.py                       # 실제 1회 수집 → 전송
.\scripts\install_task.ps1               # 상시 감시 등록 (검은 창 안 뜸)
```

웹훅 만들기: api.slack.com/apps → Create New App → Incoming Webhooks → Add New Webhook.
웹훅 없이 **로그인된 크롬**으로 보내려면 `.env` 의 `SLACK_NEWS_CHANNEL_URL` 을 채우고
크롬을 `--remote-debugging-port=9222` 로 띄워두면 된다(`pip install playwright` 필요).

## 1-2. PC 를 꺼도 돌게 (GitHub Actions)

로컬 예약작업은 노트북을 닫으면 멈춘다. **꺼도 돌아야 하면 깃허브가 대신 돌린다** — 서버도 카드도 필요 없다.

1. 이 폴더를 깃허브 저장소로 올린다 (`gh repo create news-radar --source=. --push`).
2. 저장소 → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `SLACK_WEBHOOK_URL` / Secret: 웹훅 주소
3. **Actions 탭 → 뉴스 레이더 → Run workflow** 로 한 번 손으로 돌려 확인. 그 다음부터 15분마다 자동.

- 상태(30일치 중복방지 DB)는 `actions/cache` 로 사이클 간에 이어진다. 캐시가 날아가면 그 한 사이클은 **조용히 학습만 하고 지나간다**(과거 기사 폭탄 대신 알림 한 번 거르는 쪽으로 실패).
- 깃허브 스케줄은 부하에 따라 5~15분 밀릴 수 있다. 정상이다.
- **공개 저장소면 Actions 가 무제한 무료**, 비공개면 월 2,000분까지다(15분 주기면 비공개는 초과한다 → 비공개로 갈 거면 `cron` 을 `'0,30 * * * *'` 로 낮출 것).
- 60일간 아무 커밋이 없으면 깃허브가 스케줄을 자동 정지시킨다. 알림이 조용해지면 이걸 먼저 의심할 것.
- 클라우드에서는 **웹훅만 쓸 수 있다.** Playwright(로그인된 크롬 조종) 경로는 강회장 PC 에만 있는 크롬이 필요해서 클라우드에선 불가능하다.

## 1-3. 텔레그램 (슬랙과 동시 발송)

텔레그램 토픽 **📰 세력의 정보원**(봇: 세력의 비서실장)으로도 같은 내용이 나간다. 변수가 없으면 조용히 건너뛴다.

| 환경변수 / Secret | 뜻 |
|---|---|
| `TELEGRAM_BOT_TOKEN_NEWS` | 뉴스 전용 봇 토큰. **있으면 이게 우선** |
| `TELEGRAM_BOT_TOKEN` | 공용 봇 토큰(전용 토큰이 없을 때) |
| `TELEGRAM_CHAT_ID` | 슈퍼그룹 ID (`-100…`) |
| `TELEGRAM_TOPIC_NEWS` | 토픽 스레드 ID (비우면 일반 대화방) |

- `parse_mode=HTML`, 링크 미리보기 끔. 4096자를 넘으면 **기사 경계**에서 나눠 1초 간격으로 보낸다. 429 는 `retry_after` 만큼 쉬고 1회 재시도.
- 사진: 메시지당 최대 1장(가장 중요한 기사). RSS `media:content`/`enclosure`/`media:thumbnail` → 없으면 원문 `og:image`(6초). 구글뉴스 링크는 og:image 가 안 나와서 요청하지 않는다. 사진이 실패해도 본문은 반드시 나간다.
- **seen 규칙**: 슬랙·텔레그램 중 **하나라도 성공하면 등록**. 둘 다 실패한 기사만 다음 턴 재시도. (한쪽만 실패했다고 재시도하면 성공한 쪽에 15분마다 같은 기사가 쌓인다.) 한쪽 실패는 Actions 에 `::warning::` 으로 뜬다.
- 말투는 전부 합니다체, 어려운 단어는 `radar/glossary.py` 용어집으로 처음 한 번만 괄호 풀이.
- `python run_once.py preview-telegram` → `data/outbox/preview_telegram.html` + `preview_slack.txt`. 전송도 seen 등록도 안 한다.

## 2. 명령어

| 명령 | 하는 일 |
|---|---|
| `python run_once.py dry` | 수집·채점만. **전송도 DB 기록도 안 한다** — 임계값 튜닝용 |
| `python run_once.py` | 뉴스 + 시세 1회 |
| `python run_once.py news` / `price` | 뉴스만 / 코인 급등락만 |
| `python run_once.py test` | 슬랙 연결 테스트 |
| `pythonw watch.py` | 상시 루프(창 없음). 뉴스 15분 · 시세 5분 |
| `.\scripts\install_task.ps1` | 로그인 시 자동시작 + 30분마다 생존확인 |
| `.\scripts\install_task.ps1 -Remove` / `.\scripts\stop_watch.ps1` | 해제 / 중지 |
| `python tests\test_all.py [--live]` | 자체검증 141개 (`--live` 면 실제 소스까지 146개) |

## 3. 어떻게 "큰 것만" 거르나

점수 = 토픽적합도 + 소스가중치 + 긴급도키워드 − 노이즈 + 신선도.

- **토픽 적합도**: 8개 토픽(금리·호르무즈·트럼프·비트코인·ZEC·HYPE·코인규제·AI) 키워드 히트 × 토픽 weight.
  어느 토픽에도 안 걸리면 **그 자리에서 버린다**. 짧은 영문 티커(`hype`, `btc`)는 단어경계로만 매칭해 `hyperactive` 같은 오탐을 막는다.
- **소스 가중치**: 연준 공식 +25, 바이낸스/업비트 공지 +18 — 발표처 자체가 신호다.
- **긴급도 키워드**: `속보/폭락/해킹/봉쇄/출금중단…` 제목에 있으면 만점, 본문에만 있으면 절반.
- **감점**: `전망·분석·될까·price prediction·top 10` 류 낚시성 제목 −14, 거래소 공지인데 상장폐지·입출금중단류가 아니면 −25.
- **컷**: `min_score`(60) 미만 탈락 → 60↑ 알림, 85↑ 는 🚨긴급으로 **한 건씩 따로** 발사.

## 4. 도배 방지 3중 장치 (실측으로 넣은 것)

실제로 돌려보니 한 사이클 12건 중 9건이 "연준 9월 금리인상" 한 사건의 매체별 기사였다. 그래서:

1. **제목 정규화 해시** — `[속보]`·괄호 머리표를 떼고 한글/영숫자만 남겨 해시. 매체가 달라 URL이 달라도 같은 문장이면 한 건으로 본다. 30일치 SQLite에 남는다.
2. **토픽당 상한**(`max_per_topic`, 기본 3) — 해시로 못 잡는 "같은 사건 다른 문장"을 여기서 접는다. 12건 → 8건으로 줄고 토픽이 고르게 퍼진다.
3. **전체 상한**(`max_items_per_run`, 기본 12) + **첫 실행 무음**(`first_run_silent`) — 처음 켠 날 과거 기사 폭탄을 막는다. 첫 사이클은 조용히 학습만 하고 다음 턴부터 알린다.

접힌 건들도 `seen` 에 등록하므로 다음 사이클에 되살아나지 않는다.
**전송에 실패하면 `seen` 에 등록하지 않는다** — 다음 턴에 그대로 재시도된다.

## 5. 코인 급등락 감시

- **워치리스트**(BTC/ETH/ZEC/HYPE/SOL/XRP/DOGE): 직전 체크 대비 ±2.5% 또는 24h ±8%.
- **시장 전체 스캔**: USDT 마켓 743개 중 24h ±15% & 거래대금 $30M↑ 상위 5개. 잡코인 펌핑은 거래대금이 걸러낸다.
- 같은 심볼 24h 알림은 **시간당 1회**로 제한.

## 6. 설정 (`config.json`)

| 키 | 뜻 |
|---|---|
| `min_score` / `urgent_score` | 알림 컷 60 / 긴급 컷 85 |
| `max_items_per_run` / `max_per_topic` | 사이클당 총 12건 / 토픽당 3건 |
| `interval_sec` / `price_interval_sec` | 뉴스 900초 / 시세 300초 |
| `lookback_hours` | 6시간보다 오래된 기사는 안 본다 |
| `quiet_hours` | 예: `[1,2,3,4,5,6]` → 그 시간엔 **긴급(85↑)만** 나간다 |
| `first_run_silent` | 첫 실행은 조용히 학습만 |
| `topics` | 토픽별 `queries`(검색어) · `keywords`(매칭어) · `weight` |
| `urgency_keywords` / `noise_keywords` | 가점 키워드 / 감점 키워드 |
| `sources` | 소스별 on/off |

설정은 **루프 재시작 없이** 매 사이클 다시 읽는다. 고치고 저장만 하면 반영된다.

## 7. 구조

```
config.json          설정 한 곳
radar/config.py      config.json + .env 로딩, 조용시간 판정
radar/sources.py     무료 소스 수집 (RSS는 표준 라이브러리로 직접 파싱)
radar/score.py       스코어링 + 가격 급변 판정
radar/store.py       중복 방지·상태 저장 (SQLite, data/radar.db)
radar/notify.py      알림 조립(합니다체·용어풀이) + 슬랙·텔레그램 동시 전송
radar/telegram.py    텔레그램 전송·HTML 변환·4096자 분할
radar/glossary.py    어려운 단어 풀이 용어집
radar/runner.py      한 사이클 오케스트레이션
run_once.py          1회 실행 CLI      watch.py  상시 루프(pythonw)
scripts/             숨김 실행 vbs · 예약작업 등록/해제
tests/test_all.py    자체검증 141 + 라이브 5
```

## 8. 함정 메모

- **예약작업은 반드시 `wscript.exe` + `run_hidden.vbs`**. `cmd.exe /c ...bat` 로 걸면 30분마다 검은 창이 깜빡인다.
- **30분 트리거는 감시 루프를 계속 새로 띄운다.** vbs 가 `sh.Run(..., 0, False)` 로 즉시 끝나버려서 작업 스케줄러의 `MultipleInstances IgnoreNew` 가 안 먹는다. 그래서 `watch.py` 가 `data/watch.lock` 파일잠금으로 자기 자신을 한 개로 묶는다(3번 띄워도 1개만 산다 — 테스트로 검증됨). 이 잠금이 없으면 30분마다 한 개씩 늘어난다.
- `scripts/stop_watch.ps1` 은 커맨드라인의 전체 경로로 프로세스를 찾는다. 그래서 `start_watch.bat` 은 `pythonw.exe "%~dp0..\watch.py"` 처럼 **전체 경로로** 띄운다(`pythonw watch.py` 로 띄우면 못 찾는다).
- 윈도우 SSL 인증서 이슈가 나면 `sources._get` 이 1회 `verify=False` 로 재시도한다(이미 넣어둠).
- `pythonw.exe` 에는 stdout 이 없다. 로그는 `data/watch.log` 를 보면 된다(2MB 넘으면 1회 로테이트).
- 연준 RSS가 0건으로 나오는 건 정상 — `lookback_hours` 안에 발표가 없었다는 뜻이다.
