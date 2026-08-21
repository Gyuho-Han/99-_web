"""서버 공용 실시세 소스.

.env 에 넣은 KIS 앱키 하나로 현재가·일봉을 가져온다. 사용자별 자격증명
(/keys 화면)과는 목적이 다르다. 저쪽은 "내 계좌로 주문을 낸다", 이쪽은
"모두가 같은 시장 데이터를 본다"는 용도다.

KIS는 초당 요청수 제한(실전 기준 유량 제한)이 있고 시세는 짧은 시간 안에
크게 변하지 않으므로, 프로세스 메모리에 TTL 캐시를 둔다. 조회에 실패하면
예외를 올리지 않고 None을 돌려주어 호출부가 시뮬레이터로 폴백하게 한다.
"""

from __future__ import annotations

import logging
import threading
import time

from app.brokers.base import Candle, Quote
from app.brokers.kis import KISBroker
from app.core.config import settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_broker: KISBroker | None = None
_broker_built = False

# key -> (저장시각, 값)
_quote_cache: dict[str, tuple[float, Quote]] = {}
_candle_cache: dict[str, tuple[float, list[Candle]]] = {}

# 연속 실패 시 잠깐 쉬어 간다 (키 오류로 매 요청마다 KIS를 두드리지 않도록)
_fail_count = 0
_cooldown_until = 0.0
_FAIL_LIMIT = 3
_COOLDOWN_SECONDS = 60


def _get_broker() -> KISBroker | None:
    global _broker, _broker_built
    if _broker_built:
        return _broker
    with _lock:
        if _broker_built:
            return _broker
        _broker_built = True
        if not settings.kis_market_ready:
            _broker = None
            return None
        try:
            _broker = KISBroker(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                account_no=settings.kis_account_no or "00000000-01",
                is_paper=settings.kis_market_use_paper,
            )
            log.info("KIS 실시세 활성화 (%s)", _broker.base)
        except Exception as e:  # noqa: BLE001
            log.warning("KIS 실시세 초기화 실패: %s", e)
            _broker = None
        return _broker


def is_enabled() -> bool:
    """.env 키로 실시세를 쓸 수 있는 상태인지."""
    return _get_broker() is not None


def status() -> dict:
    """프론트/헬스체크용 상태 요약. 키 값 자체는 절대 싣지 않는다."""
    enabled = is_enabled()
    return {
        "source": "kis" if enabled and not _in_cooldown() else "simulator",
        "configured": bool(settings.kis_app_key and settings.kis_app_secret),
        "enabled": enabled,
        "domain": settings.kis_paper_base if settings.kis_market_use_paper else settings.kis_real_base,
        "degraded": _in_cooldown(),
        "cached_symbols": len(_quote_cache),
    }


def _in_cooldown() -> bool:
    return time.time() < _cooldown_until


def _note_failure(what: str, err: Exception) -> None:
    global _fail_count, _cooldown_until
    _fail_count += 1
    log.warning("KIS %s 조회 실패(%d회): %s", what, _fail_count, err)
    if _fail_count >= _FAIL_LIMIT:
        _cooldown_until = time.time() + _COOLDOWN_SECONDS
        _fail_count = 0
        log.warning("KIS 연속 실패로 %d초간 시뮬레이터로 폴백합니다.", _COOLDOWN_SECONDS)


def _note_success() -> None:
    global _fail_count
    _fail_count = 0


def get_quote(symbol: str) -> Quote | None:
    """현재가. 실패하면 None (호출부가 시뮬레이터로 폴백)."""
    broker = _get_broker()
    if broker is None:
        return None

    now = time.time()
    hit = _quote_cache.get(symbol)
    if hit and now - hit[0] < settings.quote_cache_seconds:
        return hit[1]

    if _in_cooldown():
        return hit[1] if hit else None

    try:
        q = broker.get_quote(symbol)
    except Exception as e:  # noqa: BLE001
        _note_failure("현재가", e)
        return hit[1] if hit else None

    if q.price <= 0:  # 없는 종목코드거나 응답이 비어 있는 경우
        return hit[1] if hit else None

    _note_success()
    _quote_cache[symbol] = (now, q)
    return q


def get_candles(symbol: str, days: int = 120) -> list[Candle] | None:
    """일봉. 실패하면 None (호출부가 시뮬레이터로 폴백)."""
    broker = _get_broker()
    if broker is None:
        return None

    now = time.time()
    key = symbol
    hit = _candle_cache.get(key)
    # 캐시는 가장 긴 요청 길이로 채워 두고, 짧은 요청은 잘라서 준다.
    if hit and now - hit[0] < settings.candle_cache_seconds and len(hit[1]) >= days:
        return hit[1][-days:]

    if _in_cooldown():
        return hit[1][-days:] if hit else None

    want = max(days, 120)
    try:
        rows = broker.get_candles(symbol, want)
    except Exception as e:  # noqa: BLE001
        _note_failure("일봉", e)
        return hit[1][-days:] if hit else None

    if not rows:
        return hit[1][-days:] if hit else None

    _note_success()
    _candle_cache[key] = (now, rows)
    return rows[-days:]


def reset_cache() -> None:
    """키를 바꾼 뒤 재기동 없이 반영하고 싶을 때."""
    global _broker, _broker_built, _fail_count, _cooldown_until
    with _lock:
        _quote_cache.clear()
        _candle_cache.clear()
        _broker = None
        _broker_built = False
        _fail_count = 0
        _cooldown_until = 0.0
