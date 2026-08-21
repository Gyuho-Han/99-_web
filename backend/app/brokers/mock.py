"""내장 시뮬레이터 어댑터.

증권사 키가 없어도 전체 흐름(시세 → 신호 → 주문 → 체결 → 손익)을 끝까지
돌려볼 수 있게 한다. 가격은 종목코드를 시드로 하는 기하 브라운 운동으로
생성하므로 서버를 재시작해도 같은 과거 시계열이 재현된다.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.brokers.base import (
    Balance,
    BalanceItem,
    BrokerAdapter,
    Candle,
    OrderResult,
    Quote,
)
from app.models import CashAccount, Env, Position

# 데모 유니버스 — 국내 대형주 위주
UNIVERSE: dict[str, tuple[str, float]] = {
    "005930": ("삼성전자", 74_800),
    "000660": ("SK하이닉스", 197_500),
    "035420": ("NAVER", 214_000),
    "051910": ("LG화학", 382_000),
    "005380": ("현대차", 246_500),
    "035720": ("카카오", 41_300),
    "207940": ("삼성바이오로직스", 812_000),
    "068270": ("셀트리온", 178_600),
}

FEE_RATE = 0.00015    # 위탁수수료 0.015%
TAX_RATE = 0.0018     # 매도 시 증권거래세 0.18%


def _seed(symbol: str) -> int:
    return int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)


HORIZON = 520  # 항상 같은 길이의 경로를 생성해야 요청 구간이 달라도 값이 일치한다


def _series(symbol: str, days: int) -> list[Candle]:
    """종목코드 기반 결정적 일봉 시계열. 요청 길이와 무관하게 같은 경로를 낸다."""
    _, base = UNIVERSE.get(symbol, (symbol, 50_000))
    rng = random.Random(_seed(symbol))
    drift, vol = 0.0004, 0.018
    price = base * 0.82
    out: list[Candle] = []
    today = date.today()
    for i in range(HORIZON, 0, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:          # 주말 제외
            continue
        shock = rng.gauss(0, 1)
        price *= math.exp((drift - 0.5 * vol**2) + vol * shock)
        o = price * (1 + rng.gauss(0, 0.003))
        c = price
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        low = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        out.append(
            Candle(
                date=d.isoformat(),
                open=round(o, -1),
                high=round(h, -1),
                low=round(low, -1),
                close=round(c, -1),
                volume=int(abs(rng.gauss(8_000_000, 2_500_000))),
            )
        )
    return out[-days:]


class MockBroker(BrokerAdapter):
    name = "mock"

    def __init__(self, db: Session, user_id: int, env: Env):
        self.db, self.user_id, self.env = db, user_id, env

    # -- 조회 ---------------------------------------------------------------
    def verify(self) -> tuple[bool, str]:
        return True, "시뮬레이터 어댑터입니다. 증권사 자격증명 없이 동작합니다."

    def get_candles(self, symbol: str, days: int = 120) -> list[Candle]:
        return _series(symbol, days)

    def get_quote(self, symbol: str) -> Quote:
        candles = self.get_candles(symbol, 3)
        last, prev = candles[-1], candles[-2]
        name, _ = UNIVERSE.get(symbol, (symbol, 0))
        # 장중 흔들림: 분 단위로 조금씩 움직이게
        jitter = random.Random(_seed(symbol) + datetime.now().minute).gauss(0, 0.0015)
        price = round(last.close * (1 + jitter), -1)
        return Quote(
            symbol=symbol,
            name=name,
            price=price,
            prev_close=prev.close,
            open=last.open,
            high=max(last.high, price),
            low=min(last.low, price),
            volume=last.volume,
            ts=datetime.now(),
        )

    def _cash_row(self) -> CashAccount:
        row = (
            self.db.query(CashAccount)
            .filter_by(user_id=self.user_id, env=self.env)
            .one_or_none()
        )
        if row is None:
            row = CashAccount(user_id=self.user_id, env=self.env)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def get_balance(self) -> Balance:
        cash = self._cash_row().cash
        rows = (
            self.db.query(Position)
            .filter_by(user_id=self.user_id, env=self.env)
            .filter(Position.quantity > 0)
            .all()
        )
        items = [
            BalanceItem(
                symbol=p.symbol,
                name=p.name or UNIVERSE.get(p.symbol, (p.symbol, 0))[0],
                quantity=p.quantity,
                avg_price=p.avg_price,
                current_price=self.get_quote(p.symbol).price,
            )
            for p in rows
        ]
        return Balance(cash=cash, holdings=items)

    # -- 주문 ---------------------------------------------------------------
    def place_order(
        self, symbol: str, side: str, quantity: int, price: float = 0.0, order_type: str = "limit"
    ) -> OrderResult:
        if quantity <= 0:
            return OrderResult(ok=False, message="수량은 1주 이상이어야 합니다.")

        quote = self.get_quote(symbol)
        fill_price = quote.price if order_type == "market" or price <= 0 else price
        # 지정가가 시장에서 벗어나면 미체결 처리
        if order_type == "limit":
            if side == "buy" and fill_price < quote.price * 0.995:
                return OrderResult(ok=True, broker_order_id=None, message="접수됨 (미체결)")
            if side == "sell" and fill_price > quote.price * 1.005:
                return OrderResult(ok=True, broker_order_id=None, message="접수됨 (미체결)")

        cash_row = self._cash_row()
        pos = (
            self.db.query(Position)
            .filter_by(user_id=self.user_id, env=self.env, symbol=symbol)
            .one_or_none()
        )
        gross = fill_price * quantity
        fee = round(gross * FEE_RATE)

        if side == "buy":
            if cash_row.cash < gross + fee:
                return OrderResult(ok=False, message="주문 가능 금액이 부족합니다.")
            cash_row.cash -= gross + fee
            if pos is None:
                pos = Position(
                    user_id=self.user_id,
                    env=self.env,
                    symbol=symbol,
                    name=UNIVERSE.get(symbol, (symbol, 0))[0],
                    quantity=0,
                    avg_price=0.0,
                )
                self.db.add(pos)
            total_cost = pos.avg_price * pos.quantity + gross
            pos.quantity += quantity
            pos.avg_price = total_cost / pos.quantity
        else:
            if pos is None or pos.quantity < quantity:
                return OrderResult(ok=False, message="보유 수량이 부족합니다.")
            tax = round(gross * TAX_RATE)
            fee += tax
            cash_row.cash += gross - fee
            pos.quantity -= quantity
            if pos.quantity == 0:
                pos.avg_price = 0.0

        self.db.commit()
        return OrderResult(
            ok=True,
            broker_order_id=f"SIM{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}",
            filled_quantity=quantity,
            filled_price=fill_price,
            message="체결 완료",
        )

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        return OrderResult(ok=True, broker_order_id=broker_order_id, message="주문을 취소했습니다.")
