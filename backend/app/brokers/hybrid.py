"""실시세 + 모의체결 어댑터.

시세(현재가·일봉)는 .env 의 KIS 앱키로 실제 시장에서 가져오고, 예수금·보유종목·
주문 체결은 내장 시뮬레이터가 처리한다. 증권 계좌 없이도 진짜 가격 위에서
강화학습 정책을 돌려볼 수 있게 하는 것이 목적이다. 국내·미국 모두 같은 방식이다.

KIS 조회가 실패하면 조용히 시뮬레이터 시계열로 폴백한다. 시세가 잠깐 끊겼다고
에이전트 루프 전체가 멈추면 안 되기 때문이다. 폴백 여부는 `last_source` 로
확인할 수 있다.
"""

from __future__ import annotations

from app.brokers import market
from app.brokers.base import Candle, Quote
from app.brokers.mock import MockBroker
from app.models import Market


class HybridBroker(MockBroker):
    """MockBroker 를 그대로 쓰되 시세만 실제 데이터로 갈아 끼운다."""

    name = "kis-market+sim"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_source = "kis"

    @property
    def _market_key(self) -> str:
        return market.US if self.market == Market.us else market.KR

    def verify(self) -> tuple[bool, str]:
        if market.is_enabled(self._market_key):
            시장 = "미국" if self.market == Market.us else "국내"
            return True, f"KIS {시장} 실시세 + 모의체결로 동작합니다. 주문은 실제로 전송되지 않습니다."
        return True, "시뮬레이터 어댑터입니다."

    def get_quote(self, symbol: str) -> Quote:
        q = market.get_quote(symbol, self._market_key)
        if q is not None:
            self.last_source = "kis"
            return q
        self.last_source = "simulator"
        return super().get_quote(symbol)

    def get_candles(self, symbol: str, days: int = 120) -> list[Candle]:
        rows = market.get_candles(symbol, days, self._market_key)
        if rows:
            self.last_source = "kis"
            return rows
        self.last_source = "simulator"
        return super().get_candles(symbol, days)
