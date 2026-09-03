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
    currency: str = "KRW"      # KRW(국내) | USD(미국)
    exchange: str = ""         # 미국주식일 때 NAS · NYS · AMS

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
    currency: str = "KRW"

    @property
    def holdings_value(self) -> float:
        return sum(h.market_value for h in self.holdings)

    @property
    def total_equity(self) -> float:
        return self.cash + self.holdings_value


class BrokerError(RuntimeError):
    """증권사 쪽 문제로 요청이 실패했다.

    우리 코드의 버그(TypeError 같은 것)와 구분하려고 따로 둔다. 라우터는 이 예외만
    502로 바꿔 짧은 메시지를 내보내고, 나머지 예외는 원래대로 500과 스택트레이스를
    남긴다. 증권사가 잠깐 흔들린 것을 우리 버그처럼 보이게 하지 않기 위해서다.
    """


@dataclass
class Fill:
    """접수된 주문의 현재 체결 상태.

    증권사 주문 API는 "접수했다"까지만 알려 준다. 얼마나 체결됐는지는 체결조회를
    따로 불러야 알 수 있어서, 그 결과를 담는 그릇이 하나 필요하다.
    """

    broker_order_id: str
    ordered_quantity: int = 0
    filled_quantity: int = 0
    filled_price: float = 0.0     # 체결 평균단가
    canceled: bool = False


@dataclass
class OrderResult:
    ok: bool
    broker_order_id: str | None = None
    filled_quantity: int = 0
    filled_price: float = 0.0
    message: str = ""

    # 아래 셋은 즉시 체결되는 시뮬레이터만 채운다. 실제 증권사는 접수까지만
    # 알려 주므로 0으로 남고, 체결 폴링도 실현손익은 채우지 않는다
    # (매도 시점의 취득단가를 증권사 잔고가 갖고 있어서다 — services/fills.py 참고).
    fee: float = 0.0
    tax: float = 0.0
    realized_pnl: float = 0.0


class BrokerAdapter(ABC):
    """모든 증권사 어댑터가 구현해야 하는 계약.

    국내주식과 미국주식은 통화·거래시간·엔드포인트가 다르지만 이 인터페이스는
    같다. 시장별 차이는 어댑터 구현체 안에서 흡수한다.
    """

    name: str = "base"
    currency: str = "KRW"

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

    def get_fills(self, broker_order_ids: list[str]) -> dict[str, Fill]:
        """접수된 주문들의 체결 상태를 한 번에 조회한다.

        추상 메서드가 아니라 기본 구현을 둔 이유: 시뮬레이터 어댑터는 주문을 내는
        즉시 체결시키므로 미체결이라는 상태 자체가 없다. 조회할 것이 없는 어댑터는
        이 기본 구현(빈 dict)을 그대로 쓰면 된다.

        반환값은 broker_order_id -> Fill. 조회되지 않은 주문은 키가 없다.
        """
        return {}
