"""데모 계정과 과거 데이터 생성.

심사·시연에서 빈 화면을 보지 않도록 6개월치 자산곡선·주문·신호를 만들어 둔다.
결정적 시드를 쓰므로 재실행해도 같은 결과가 나온다.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.brokers.mock import UNIVERSE, _series
from app.core.security import hash_password
from app.models import (
    AgentAction,
    AgentConfig,
    AgentSignal,
    CashAccount,
    EquitySnapshot,
    Env,
    Market,
    Order,
    OrderStatus,
    Position,
    Side,
    User,
)

DEMO_EMAIL = "demo@kairo.dev"
DEMO_PASSWORD = "kairo1234"
START_EQUITY = 10_000_000      # 국내 초기 예수금 (KRW)
US_START_EQUITY = 10_000.0     # 미국 초기 예수금 (USD)

# 시장별 (기본 유니버스, 거래시간). 미국 정규장은 한국 시간으로 밤이다.
MARKET_DEFAULTS = {
    Market.kr: ("005930,000660,035420", "09:05", "15:15"),
    Market.us: ("AAPL,NVDA,MSFT", "22:35", "04:55"),
}


def seed_if_empty(db: Session) -> None:
    if db.query(User).filter_by(email=DEMO_EMAIL).first():
        return

    user = User(
        email=DEMO_EMAIL,
        name="데모 계정",
        password_hash=hash_password(DEMO_PASSWORD),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 환경 2종 × 시장 2종 = 네 조합에 각각 예수금과 에이전트 설정을 만들어 둔다.
    for env in (Env.paper, Env.live):
        for mkt in (Market.kr, Market.us):
            seed_cash = US_START_EQUITY if mkt == Market.us else START_EQUITY
            universe, start, end = MARKET_DEFAULTS[mkt]
            db.add(
                CashAccount(
                    user_id=user.id, env=env, market=mkt,
                    cash=seed_cash, deposit_total=seed_cash,
                )
            )
            db.add(
                AgentConfig(
                    user_id=user.id,
                    env=env,
                    market=mkt,
                    universe=universe,
                    trading_start=start,
                    trading_end=end,
                    enabled=False,
                )
            )
    db.commit()

    # 과거 데이터는 국내 모의투자에만 만들어 둔다. 미국은 빈 상태에서 시작한다.
    _seed_history(db, user.id, Env.paper)
    db.commit()


def _seed_history(db: Session, user_id: int, env: Env) -> None:
    rng = random.Random(20260319)
    symbols = ["005930", "000660", "035420"]
    series = {s: {c.date: c for c in _series(s, 260)} for s in symbols}
    trading_days = sorted(series["005930"])[-180:]

    # 벤치마크: 첫날 전량 매수 후 보유(Buy & Hold)
    bench_base = sum(series[s][trading_days[0]].close for s in symbols) / len(symbols)

    cash = float(START_EQUITY)
    holdings: dict[str, tuple[int, float]] = {}  # symbol -> (qty, avg)
    equity_prev = float(START_EQUITY)

    for i, d in enumerate(trading_days):
        day = date.fromisoformat(d)
        for s in symbols:
            c = series[s][d]
            hist = [series[s][x].close for x in trading_days[max(0, i - 25): i + 1]]
            if len(hist) < 21:
                continue
            sma5 = sum(hist[-5:]) / 5
            sma20 = sum(hist[-20:]) / 20
            prev5 = sum(hist[-6:-1]) / 5
            prev20 = sum(hist[-21:-1]) / 20
            edge = (sma5 / sma20 - 1) * 100
            qty, avg = holdings.get(s, (0, 0.0))
            ret = (c.close / avg - 1) if qty and avg else 0.0

            golden = sma5 > sma20 and prev5 <= prev20
            dead = sma5 < sma20 and prev5 >= prev20

            action, conf = "hold", 0.5
            if golden and not qty:
                action, conf = "buy", min(0.95, 0.6 + abs(edge) / 6)
            elif qty and (dead or ret < -0.06 or ret > 0.14):
                action, conf = "sell", min(0.95, 0.6 + abs(edge) / 6)

            price = c.close
            executed = False
            if action == "buy":
                budget = min(cash, 2_000_000)
                n = int(budget // price)
                if n >= 1:
                    cost = n * price
                    fee = round(cost * 0.00015)
                    cash -= cost + fee
                    new_qty = qty + n
                    holdings[s] = (new_qty, (avg * qty + cost) / new_qty)
                    executed = True
                    db.add(
                        Order(
                            user_id=user_id, env=env, market=Market.kr, broker_order_id=f"SEED{i:04d}{s[-2:]}",
                            symbol=s, name=UNIVERSE[s][0], side=Side.buy, order_type="limit",
                            quantity=n, price=price, filled_quantity=n, filled_price=price,
                            fee=fee, status=OrderStatus.filled, source="agent",
                            note=f"5일선 우위 {edge:+.2f}% (신뢰도 {conf:.2f})",
                            created_at=datetime.combine(day, datetime.min.time()).replace(hour=10),
                            filled_at=datetime.combine(day, datetime.min.time()).replace(hour=10),
                        )
                    )
            elif action == "sell" and qty:
                gross = qty * price
                fee = round(gross * (0.00015 + 0.0018))
                realized = round((price - avg) * qty - fee)
                cash += gross - fee
                holdings[s] = (0, 0.0)
                executed = True
                db.add(
                    Order(
                        user_id=user_id, env=env, market=Market.kr, broker_order_id=f"SEED{i:04d}{s[-2:]}S",
                        symbol=s, name=UNIVERSE[s][0], side=Side.sell, order_type="limit",
                        quantity=qty, price=price, filled_quantity=qty, filled_price=price,
                        fee=fee, realized_pnl=realized, status=OrderStatus.filled, source="agent",
                        note=f"추세 이탈 {edge:+.2f}% (신뢰도 {conf:.2f})",
                        created_at=datetime.combine(day, datetime.min.time()).replace(hour=13),
                        filled_at=datetime.combine(day, datetime.min.time()).replace(hour=13),
                    )
                )

            # 최근 10거래일 신호만 저장 (신호 테이프용)
            if i >= len(trading_days) - 10:
                spread = abs(edge) / 4
                db.add(
                    AgentSignal(
                        user_id=user_id, env=env, market=Market.kr, symbol=s,
                        action=AgentAction(action), confidence=round(conf, 3),
                        q_buy=round(edge / 2 + rng.gauss(0, 0.15), 3),
                        q_hold=0.25,
                        q_sell=round(-edge / 2 + rng.gauss(0, 0.15), 3),
                        price=price, executed=executed,
                        reason=f"SMA 격차 {edge:+.2f}% · 변동성 {spread:.2f}",
                        created_at=datetime.combine(day, datetime.min.time()).replace(
                            hour=9 + (i % 6), minute=(i * 7) % 60
                        ),
                    )
                )

        hv = sum(q * series[s][d].close for s, (q, _) in holdings.items())
        equity = cash + hv
        bench_now = sum(series[s][d].close for s in symbols) / len(symbols)
        db.add(
            EquitySnapshot(
                user_id=user_id, env=env, market=Market.kr, date=day,
                cash=round(cash), holdings_value=round(hv), total_equity=round(equity),
                benchmark_value=round(START_EQUITY * bench_now / bench_base),
            )
        )
        equity_prev = equity

    for s, (q, avg) in holdings.items():
        if q:
            db.add(
                Position(user_id=user_id, env=env, market=Market.kr, symbol=s, name=UNIVERSE[s][0],
                         quantity=q, avg_price=avg)
            )

    cash_row = db.query(CashAccount).filter_by(user_id=user_id, env=env, market=Market.kr).one()
    cash_row.cash = round(cash)
    _ = math, equity_prev, timedelta  # 정적 분석 경고 억제
