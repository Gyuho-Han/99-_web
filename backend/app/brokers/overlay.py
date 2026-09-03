"""계좌 어댑터 + 서버 공용 실시세.

왜 나눠야 하는가
----------------
KIS 모의투자 도메인(openapivts)은 **시세조회를 제대로 지원하지 않는다.**
`inquire-price` 와 `inquire-daily-itemchartprice` 가 간헐적으로 500을 돌려준다.
그런데 /keys 화면에서 모의투자 계좌를 등록하면 그 자격증명으로 만든 어댑터가
시세까지 담당하게 되어, 계좌를 붙이는 순간 차트와 현재가가 깨졌다.

시세는 어느 계좌를 붙였든 같은 값이다. 그래서 이렇게 나눈다.

  예수금 · 보유 · 주문 · 취소 · 체결  →  사용자 계좌 어댑터 (모의/실계좌 도메인)
  현재가 · 일봉                        →  .env 실전 앱키로 도는 서버 공용 소스

공용 소스는 캐시(현재가 3초 · 일봉 5분)와 연속 실패 시 쿨다운을 이미 갖고 있어서,
에이전트 루프가 매 틱 돌아도 실제 호출은 그만큼만 나간다.

폴백을 하지 않는 이유
--------------------
공용 소스가 잠시 막혔을 때 시뮬레이터 가격으로 내려가면, 실제 계좌가 붙어 있는
상태에서 가짜 가격으로 주문을 낼 수 있다. 값이 틀린 채로 조용히 도는 것보다
"지금은 시세를 못 가져온다"고 실패하는 편이 안전하다. 그래서 BrokerError 를 올린다.
"""

from __future__ import annotations

from app.brokers import market as market_source
from app.brokers.base import (
    Balance,
    BrokerAdapter,
    BrokerError,
    Candle,
    Fill,
    OrderResult,
    Quote,
)
from app.models import Market


def market_key(market: Market) -> str:
    return market_source.US if market == Market.us else market_source.KR


class MarketDataBroker(BrokerAdapter):
    """계좌 호출은 그대로 넘기고, 시세만 서버 공용 소스에서 가져온다."""

    def __init__(self, account: BrokerAdapter, market: Market):
        self._account = account
        self._key = market_key(market)
        self.name = f"{account.name}+quotes"
        self.currency = account.currency

    # -- 계좌: 그대로 위임 ---------------------------------------------------
    def verify(self) -> tuple[bool, str]:
        return self._account.verify()

    def get_balance(self) -> Balance:
        return self._account.get_balance()

    def place_order(
        self, symbol: str, side: str, quantity: int, price: float = 0.0, order_type: str = "limit"
    ) -> OrderResult:
        return self._account.place_order(symbol, side, quantity, price, order_type)

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        return self._account.cancel_order(broker_order_id)

    def get_fills(self, broker_order_ids: list[str]) -> dict[str, Fill]:
        return self._account.get_fills(broker_order_ids)

    # -- 시세: 공용 소스 -----------------------------------------------------
    def get_quote(self, symbol: str) -> Quote:
        q = market_source.get_quote(symbol, self._key)
        if q is None:
            raise BrokerError(_why("현재가", self._key, symbol))
        return q

    def get_candles(self, symbol: str, days: int = 120) -> list[Candle]:
        rows = market_source.get_candles(symbol, days, self._key)
        if not rows:
            raise BrokerError(_why("일봉", self._key, symbol))
        return rows


def _why(what: str, key: str, symbol: str) -> str:
    """왜 못 가져왔는지 화면에 그대로 띄울 수 있는 한 문장으로."""
    info = market_source.status(key)
    if info["degraded"]:
        return (
            f"{symbol} {what}를 가져오지 못했습니다. KIS 조회가 연속 실패해 "
            f"{info['retry_in']}초 뒤 다시 시도합니다."
            + (f" (사유: {info['last_error']})" if info["last_error"] else "")
        )
    return f"{symbol} {what}를 가져오지 못했습니다. 종목코드와 장 운영시간을 확인하세요."
