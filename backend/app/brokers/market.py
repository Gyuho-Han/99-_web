"""서버 공용 실시세 소스 (국내 · 미국).

.env 에 넣은 KIS 앱키 하나로 두 시장의 현재가·일봉을 모두 가져온다. 미국주식도
같은 앱키를 쓰므로 추가로 발급받을 키는 없다. 사용자별 자격증명(/keys 화면)과는
목적이 다르다. 저쪽은 "내 계좌로 주문을 낸다", 이쪽은 "모두가 같은 시장 데이터를
본다"는 용도다.

KIS는 초당 요청수 제한이 있고 시세는 짧은 시간 안에 크게 변하지 않으므로,
프로세스 메모리에 TTL 캐시를 둔다. 조회에 실패하면 예외를 올리지 않고 None을
돌려주어 호출부가 시뮬레이터로 폴백하게 한다. 캐시와 실패 카운터는 시장별로
따로 관리하므로, 미국 시세가 막혀도 국내 시세는 그대로 나간다.
"""

from __future__ import annotations

import logging
import threading
import time

from app.brokers.base import BrokerAdapter, Candle, Quote
from app.brokers.kis import KISBroker
from app.brokers.kis_overseas import KISOverseasBroker
from app.core.config import settings

log = logging.getLogger(__name__)

KR = "kr"
US = "us"
MARKETS = (KR, US)

_lock = threading.Lock()

# 실패는 즉시 기억한다. 한 번 막힌 KIS를 매 요청마다 다시 두드리면
# 그때마다 타임아웃만큼 화면이 멈춘다.
_FAIL_LIMIT = 2
_COOLDOWN_SECONDS = 60


class _Source:
    """한 시장의 실시세 어댑터 + 캐시 + 실패 상태."""

    def __init__(self, market: str):
        self.market = market
        self.broker: BrokerAdapter | None = None
        self.built = False
        self.quotes: dict[str, tuple[float, Quote]] = {}
        self.candles: dict[str, tuple[float, list[Candle]]] = {}
        self.fail_count = 0
        self.cooldown_until = 0.0
        self.last_error: str | None = None

    # -- 어댑터 --------------------------------------------------------------
    @property
    def ready(self) -> bool:
        return settings.us_market_ready if self.market == US else settings.kis_market_ready

    def get_broker(self) -> BrokerAdapter | None:
        if self.built:
            return self.broker
        with _lock:
            if self.built:
                return self.broker
            self.built = True
            if not self.ready:
                self.broker = None
                return None
            try:
                if self.market == US:
                    self.broker = KISOverseasBroker(
                        app_key=settings.kis_app_key,
                        app_secret=settings.kis_app_secret,
                        account_no=settings.kis_overseas_account_no or "00000000-01",
                        is_paper=settings.kis_market_use_paper,
                    )
                else:
                    self.broker = KISBroker(
                        app_key=settings.kis_app_key,
                        app_secret=settings.kis_app_secret,
                        account_no=settings.kis_account_no or "00000000-01",
                        is_paper=settings.kis_market_use_paper,
                    )
                log.info("KIS 실시세 활성화 [%s] (%s)", self.market, self.broker.base)
            except Exception as e:  # noqa: BLE001
                log.warning("KIS 실시세 초기화 실패 [%s]: %s", self.market, e)
                self.broker = None
            return self.broker

    # -- 실패 관리 -----------------------------------------------------------
    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def note_failure(self, what: str, err: Exception) -> None:
        self.fail_count += 1
        self.last_error = f"{what} 조회 실패: {err}"
        log.warning("KIS %s 조회 실패 [%s] (%d회): %s", what, self.market, self.fail_count, err)
        if self.fail_count >= _FAIL_LIMIT:
            self.cooldown_until = time.time() + _COOLDOWN_SECONDS
            self.fail_count = 0
            log.warning(
                "KIS 연속 실패로 [%s] 시세를 %d초간 시뮬레이터로 폴백합니다.",
                self.market,
                _COOLDOWN_SECONDS,
            )

    def note_success(self) -> None:
        self.fail_count = 0
        self.last_error = None

    def reset(self) -> None:
        self.quotes.clear()
        self.candles.clear()
        self.broker = None
        self.built = False
        self.fail_count = 0
        self.cooldown_until = 0.0
        self.last_error = None


_SOURCES: dict[str, _Source] = {m: _Source(m) for m in MARKETS}


def _src(market: str | None) -> _Source:
    return _SOURCES.get(str(market or KR), _SOURCES[KR])


# --------------------------------------------------------------------------
# 공개 API
# --------------------------------------------------------------------------
def is_enabled(market: str = KR) -> bool:
    """해당 시장의 실시세를 .env 키로 쓸 수 있는 상태인지."""
    return _src(market).get_broker() is not None


def status(market: str = KR) -> dict:
    """프론트/헬스체크용 상태 요약. 키 값 자체는 절대 싣지 않는다."""
    s = _src(market)
    enabled = is_enabled(s.market)
    return {
        "market": s.market,
        "source": "kis" if enabled and not s.in_cooldown() else "simulator",
        "configured": settings.kis_keys_present,
        "enabled": enabled,
        "domain": settings.kis_paper_base if settings.kis_market_use_paper else settings.kis_real_base,
        "degraded": s.in_cooldown(),
        "cached_symbols": len(s.quotes),
        "currency": "USD" if s.market == US else "KRW",
        # 왜 시뮬레이터로 내려갔는지 화면에서 바로 보이게 한다. 앱키 값은 담기지 않는다.
        "last_error": s.last_error,
        "retry_in": max(0, int(s.cooldown_until - time.time())) if s.in_cooldown() else 0,
    }


def get_quote(symbol: str, market: str = KR) -> Quote | None:
    """현재가. 실패하면 None (호출부가 시뮬레이터로 폴백)."""
    s = _src(market)
    broker = s.get_broker()
    if broker is None:
        return None

    now = time.time()
    hit = s.quotes.get(symbol)
    if hit and now - hit[0] < settings.quote_cache_seconds:
        return hit[1]

    if s.in_cooldown():
        return hit[1] if hit else None

    try:
        q = broker.get_quote(symbol)
    except Exception as e:  # noqa: BLE001
        s.note_failure("현재가", e)
        return hit[1] if hit else None

    if q.price <= 0:  # 없는 종목코드거나 응답이 비어 있는 경우
        return hit[1] if hit else None

    s.note_success()
    s.quotes[symbol] = (now, q)
    return q


def get_candles(symbol: str, days: int = 120, market: str = KR) -> list[Candle] | None:
    """일봉. 실패하면 None (호출부가 시뮬레이터로 폴백)."""
    s = _src(market)
    broker = s.get_broker()
    if broker is None:
        return None

    now = time.time()
    hit = s.candles.get(symbol)
    # 캐시는 가장 긴 요청 길이로 채워 두고, 짧은 요청은 잘라서 준다.
    if hit and now - hit[0] < settings.candle_cache_seconds and len(hit[1]) >= days:
        return hit[1][-days:]

    if s.in_cooldown():
        return hit[1][-days:] if hit else None

    want = max(days, 100)
    try:
        rows = broker.get_candles(symbol, want)
    except Exception as e:  # noqa: BLE001
        s.note_failure("일봉", e)
        return hit[1][-days:] if hit else None

    if not rows:
        return hit[1][-days:] if hit else None

    s.note_success()
    s.candles[symbol] = (now, rows)
    return rows[-days:]


def reset_cache(market: str | None = None) -> None:
    """키를 바꾼 뒤 재기동 없이 반영하고 싶을 때."""
    with _lock:
        targets = [_src(market)] if market else list(_SOURCES.values())
        for s in targets:
            s.reset()
