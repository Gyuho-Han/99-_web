"""증권사 어댑터 인터페이스.

실 증권사 연동과 모의 시뮬레이터를 같은 인터페이스로 다룬다.
강화학습 에이전트와 API 라우터는 이 추상 타입만 알면 되고,
증권사가 바뀌어도 어댑터 구현체 하나만 추가하면 된다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: int
    ts: datetime

    @property
    def change(self) -> float:
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close * 100) if self.prev_close else 0.0


@dataclass
class Candle:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class BalanceItem:
    symbol: str
    name: str
    quantity: int
    avg_price: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pct(self) -> float:
        return ((self.current_price / self.avg_price) - 1) * 100 if self.avg_price else 0.0


@dataclass
class Balance:
    cash: float
    holdings: list[BalanceItem] = field(default_factory=list)

    @property
    def holdings_value(self) -> float:
        return sum(h.market_value for h in self.holdings)

    @property
    def total_equity(self) -> float:
        return self.cash + self.holdings_value


@dataclass
class OrderResult:
    ok: bool
    broker_order_id: str | None = None
    filled_quantity: int = 0
    filled_price: float = 0.0
    message: str = ""


class BrokerAdapter(ABC):
    """모든 증권사 어댑터가 구현해야 하는 계약."""

    name: str = "base"

    @abstractmethod
    def verify(self) -> tuple[bool, str]:
        """자격증명 유효성 검사. (성공여부, 메시지)"""

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """현재가 조회."""

    @abstractmethod
    def get_candles(self, symbol: str, days: int = 120) -> list[Candle]:
        """일봉 조회. 강화학습 상태벡터 구성의 입력."""

    @abstractmethod
    def get_balance(self) -> Balance:
        """예수금 및 보유종목 조회."""

    @abstractmethod
    def place_order(
        self, symbol: str, side: str, quantity: int, price: float = 0.0, order_type: str = "limit"
    ) -> OrderResult:
        """주문 전송. price=0 이고 order_type='market' 이면 시장가."""

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> OrderResult:
        """주문 취소."""
