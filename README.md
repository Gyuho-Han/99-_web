# KAIRO — 강화학습 자동매매 콘솔

한국투자증권 KIS Open API와 연결되는 자동매매 시스템입니다. 학습한 강화학습 정책을
서버에 등록하면 바로 실거래 파이프라인에 올라갑니다. 지금은 정책 자리에 규칙 기반
베이스라인이 들어가 있고, 증권사 자격증명이 없어도 내장 시뮬레이터로 전체 흐름이 돕니다.

```
시세 조회 → 상태벡터 구성 → 정책 추론 → 리스크 게이트 → 주문 전송 → 체결·손익 기록
```

---

## 빠르게 실행

```bash
./run.sh
```

- 백엔드 http://localhost:8000 (API 문서 `/docs`)
- 프론트엔드 http://localhost:5173
- 데모 계정 `demo@kairo.dev` / `kairo1234` — 6개월치 자산곡선·주문·신호가 미리 들어 있습니다

수동으로 띄우려면:

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

---

## 실시세 붙이기 (.env)

기본값은 내장 시뮬레이터 가격이다. `backend/.env` 에 KIS 앱키만 넣으면 현재가와
일봉이 실제 시장 데이터로 바뀐다. **계좌번호는 필요 없고, 주문은 여전히
시뮬레이터가 처리하므로 진짜 돈이 나가지 않는다.**

```bash
cd backend
cp .env.example .env      # 이미 .env 가 있으면 생략
```

```dotenv
KIS_APP_KEY=발급받은-앱키
KIS_APP_SECRET=발급받은-시크릿
```

> **실전투자 앱키를 넣어야 한다.** KIS 시세조회 API는 모의투자 도메인
> (`openapivts`)에서 지원하지 않는다. 모의투자 앱키를 넣으면 시세 조회가 실패하고
> 자동으로 시뮬레이터로 되돌아간다.

키를 넣고 바로 확인:

```bash
cd backend && python scripts/check_kis.py          # 삼성전자
cd backend && python scripts/check_kis.py 000660   # 종목 지정
```

성공하면 서버를 띄웠을 때 상단바에 **실시세** 배지가 뜬다. 시뮬레이터로 동작 중이면
회색 **시뮬레이터** 배지가 뜬다. 배지에 마우스를 올리면 왜 그 상태인지 알려 준다.

### 동작 방식

| | 시세(현재가·일봉) | 예수금·보유·체결 |
|---|---|---|
| 키 없음 | 시뮬레이터 | 시뮬레이터 |
| `.env` 앱키만 | **실제 KIS** | 시뮬레이터 |
| `/keys` 화면에서 개인 자격증명 등록 | 실제 KIS | **실제 계좌** |

`.env` 앱키는 서버 전체가 공유하는 시세용이고, `/keys` 화면의 자격증명은 사용자별
주문용이다. 둘은 별개이며 개인 자격증명이 있으면 그쪽이 우선한다.

### 그 밖의 옵션

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KIS_ACCOUNT_NO` | 빈 값 | 잔고·주문까지 실제로 붙일 때만. 예 `12345678-01` |
| `KIS_MARKET_DATA` | `true` | `false` 로 두면 키를 지우지 않고도 시뮬레이터로 되돌린다 |
| `KIS_MARKET_USE_PAPER` | `false` | 시세 조회 도메인. 기본은 실전 |
| `QUOTE_CACHE_SECONDS` | `3` | 현재가 캐시. KIS 초당 요청 제한 대응 |
| `CANDLE_CACHE_SECONDS` | `300` | 일봉 캐시 |

### 알아 둘 것

- **캐시**: KIS는 초당 요청수 제한이 있어 현재가 3초, 일봉 5분 캐시를 둔다. 에이전트
  루프가 매 틱 돌아도 실제 호출은 그만큼만 나간다.
- **폴백**: KIS 조회가 실패하면 예외를 올리지 않고 시뮬레이터 시계열로 조용히
  내려간다. 연속 3회 실패하면 60초간 쉬었다가 다시 시도한다. 시세가 잠깐 끊겼다고
  에이전트 루프 전체가 멈추면 안 되기 때문이다.
- **일봉 100건 제한**: KIS 일봉 API는 1회 요청당 100건이 상한이다. 그보다 긴 구간이
  필요하면 `app/brokers/kis.py` 의 `get_candles` 에서 구간을 나눠 여러 번 호출하도록
  고쳐야 한다.
- **장 시간**: 장이 닫혀 있으면 현재가는 종가로 고정된다. 정상이다.
- `.env` 는 `.gitignore` 에 있어 커밋되지 않는다. 앱키는 API 응답 어디에도 실리지
  않는다 (`/api/market/status` 는 출처와 도메인만 돌려준다).

---

## 화면

| 경로 | 하는 일 |
|---|---|
| `/` 인사이트 | 평가자산·손익·Sharpe, 자산곡선, 신호 테이프, 보유종목, 최근 주문 |
| `/agent` 에이전트 | 자동매매 on/off, 정책 모델 선택, 대상 종목, 리스크 한도, 미리 실행 |
| `/trade` 주문 | 실시간 시세, 지정가·시장가 주문표, 수수료 포함 예상 금액, 2단계 확인 |
| `/orders` 거래 내역 | 출처·구분·상태 필터, 페이지네이션, CSV 내려받기 |
| `/performance` 수익 분석 | Sharpe·Sortino·MDD·Calmar·손익비, 낙폭 곡선, 월별 수익률, Buy & Hold 비교 |
| `/keys` API 키 | KIS 자격증명 등록·연결 테스트·삭제 (모의/실계좌 별도) |

상단 토글로 **모의투자 / 실계좌**를 전환합니다. 두 환경은 자격증명·포지션·주문·설정·
스냅샷이 전부 분리되어 있고, 실계좌일 때는 상단에 붉은 경고 띠가 붙습니다.

---

## 강화학습 모델 붙이기

`backend/app/agent/policy.py` 한 파일만 건드리면 됩니다.

```python
class PPOEnsemblePolicy(Policy):
    name = "ppo-ensemble-v1"

    def __init__(self, ckpt):
        self.net = torch.load(ckpt); self.net.eval()

    def act(self, obs: Observation) -> PolicyOutput:
        x = build_state_vector(obs)          # OHLCV + 지표 + 감성 + 에이전트 상태
        logits = self.net(x)
        probs = softmax(logits)
        action = ["buy", "hold", "sell"][int(probs.argmax())]
        return PolicyOutput(
            action=action,
            confidence=float(probs.max()),
            q_values=dict(zip(["buy", "hold", "sell"], logits.tolist())),
            reason="PPO ensemble",
        )

register_policy("ppo-ensemble-v1", PPOEnsemblePolicy("checkpoints/ppo.pt"))
```

등록하면 에이전트 화면의 정책 선택 드롭다운에 자동으로 나타납니다.

**`Observation`이 넘겨 주는 것**

| 필드 | 내용 |
|---|---|
| `candles` | 최근 N일 일봉 (오래된 → 최신) |
| `price` | 현재가 |
| `cash_ratio`, `position_ratio`, `unrealized_pct` | 에이전트 상태변수 |
| `sentiment` | 뉴스 감성 극성 스칼라 `s_t ∈ [-1, 1]` — **아직 0으로 고정** |
| `features` | SMA5/20/60, RSI14, MACD, 볼린저 위치, 변동성, 모멘텀 |

감성 값은 `app/agent/runner.py`의 `sentiment=0.0` 자리에 KR-FinBert-SC 일별 집계값을
넣으면 됩니다 (`# TODO` 표시). 네이버 검색 API로 당일 기사를 모으고, 문장 단위로
분리해 추론한 뒤 평균이나 가중합으로 하나의 스칼라를 만들어 주입하는 흐름입니다.

**스케일러 주의**: 정규화 파라미터는 학습 구간에서만 적합시켜야 합니다. 추론 시점에
전체 구간 통계를 쓰면 lookahead bias가 들어갑니다.

---

## 리스크 게이트

정책 출력이 그대로 주문이 되지 않습니다. `app/agent/runner.py`에서 순서대로 검사합니다.

1. 자동매매 활성화 여부
2. 거래 시간 (`trading_start` ~ `trading_end`)
3. 신뢰도 ≥ `confidence_threshold`
4. 일일 손실 한도 미도달
5. 종목당 비중 한도 · 1회 주문금액 한도 · 예수금

하나라도 걸리면 **신호는 기록하되 주문은 내지 않습니다** (`executed=False`, `reason`에
차단 사유 기록). 대시보드의 신호 테이프에서 임계선 아래의 흐린 막대가 바로 그것입니다.

---

## 증권사 어댑터

```
BrokerAdapter (ABC)
├── KISBroker    실계좌 / 모의투자 도메인·TR_ID 분기, 토큰 캐싱
└── MockBroker   결정적 GBM 시세 + 체결·수수료·세금 시뮬레이션
```

자격증명이 없으면 `factory.get_broker()`가 자동으로 `MockBroker`를 돌려줍니다. 다른
증권사를 붙이려면 `BrokerAdapter`를 구현한 클래스 하나만 추가하면 됩니다.

> **KIS TR_ID 확인 필요**: KIS는 TR_ID와 응답 필드명을 개편한 이력이 있습니다.
> `app/brokers/kis.py` 상단의 `_TR` 표를 연동 전에 KIS 개발자센터 최신 문서와
> 한 번 대조하세요. 주문/취소 TR_ID가 특히 그렇습니다.

---

## 자격증명 보관

- App Secret과 계좌번호는 **Fernet(AES-128-CBC + HMAC)** 으로 암호화해 저장
- 복호화 키(`MASTER_KEY`)는 DB가 아니라 환경변수
- 어떤 API 응답에도 평문이 실리지 않음 — 마스킹된 값만 반환
- 자격증명 등록·검증·삭제와 자동매매 토글은 `audit_logs`에 기록

`MASTER_KEY`를 지정하지 않으면 기동할 때마다 새로 생성되므로, 재시작 시 기존
암호문을 복호화할 수 없습니다. `.env.example`을 복사해 값을 채워 두세요.

---

## 성과 지표

`app/services/metrics.py`. 절대수익이 아니라 위험조정수익을 기준으로 봅니다.

| 지표 | 정의 |
|---|---|
| Sharpe | (초과수익 평균 ÷ 표준편차) × √252, 무위험수익률 연 3.2% 가정 |
| Sortino | 하방 편차만 분모로 |
| MDD | 고점 대비 최대 낙폭 |
| Calmar | 연환산 수익률 ÷ \|MDD\| |
| Profit Factor | 총이익 ÷ 총손실 |

벤치마크는 첫날 균등 매수 후 보유하는 Buy & Hold입니다. 상승장에서는 강화학습
전략이 벤치마크를 밑도는 것이 정상이며, 비교는 Sharpe와 MDD에서 하는 것이 맞습니다.

---

## 디자인

- **색**: 뉴트럴 니어블랙(`#0a0a0c`) 바탕에 시안(`#22d3ee`) 한 가지를 인터페이스
  액센트로 사용. 채도 있는 색은 시장 데이터에만 씁니다.
- **등락 표기**: 국내 관례를 따라 **상승 적색 / 하락 청색**. 레퍼런스 이미지는
  상승 초록이지만, 국내 주식 서비스에서 관례를 뒤집으면 오독 위험이 큽니다.
- **타이포**: IBM Plex Sans KR (본문) + IBM Plex Mono (모든 숫자, tabular-nums).
  금액은 정수부를 크게, 단위를 작게 조판합니다.
- **시그니처**: 신호 테이프. 정책의 매 스텝 출력을 막대로 늘어놓고 실행 임계값을
  점선으로 그어, 주문이 왜 나가지 않았는지가 한눈에 읽히게 했습니다.
- 라이트 테마, 키보드 포커스 링, `prefers-reduced-motion` 대응 포함.

---

## 구조

```
backend/
  .env        실시세 앱키 등 (git 제외)
  scripts/    check_kis.py — 앱키 점검
  app/
    core/       설정, 암호화·JWT
    db/         SQLAlchemy 세션
    models/     ORM (사용자, 자격증명, 포지션, 주문, 신호, 스냅샷, 감사로그)
    brokers/    base(ABC) · kis · market(실시세+캐시) · hybrid(실시세+모의체결) · mock · factory
    agent/      policy(모델 연결 지점) · runner(리스크 게이트 + 루프)
    services/   metrics · seed
    api/        auth · credentials · trading · insight
frontend/
  src/
    lib/        api 클라이언트 · 포맷터 · 전역 컨텍스트
    components/ ui · Shell · Charts · SignalTape
    pages/      Login · Dashboard · Agent · Trade · Orders · Performance · Keys
```

---

## 남은 일

- [ ] KIS 일봉 100건 제한 우회 (구간 분할 호출) — 현재는 최근 100영업일까지
- [ ] KR-FinBert-SC 감성 파이프라인을 `sentiment` 필드에 연결
- [ ] KIS 체결 조회(`inquire-daily-ccld`)로 미체결 주문 상태 폴링
- [ ] 일별 `EquitySnapshot` 자동 적재 스케줄러 (현재는 시드만 존재)
- [ ] 학습한 PPO/DQN 체크포인트 등록
- [ ] 실계좌 투입 전 모의투자에서 최소 수 주 이상 검증

---

이 시스템은 학습·연구 목적으로 만들어졌습니다. 실계좌 연결은 손실 가능성을
충분히 이해한 뒤에, 감당할 수 있는 금액으로만 시작하세요.
