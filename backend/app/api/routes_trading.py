"""시세 · 계좌 · 주문."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import current_user, env_param
from app.brokers import market
from app.brokers.factory import get_broker, is_live_broker, market_source
from app.brokers.mock import UNIVERSE
from app.db.session import get_db
from app.models import CashAccount, EquitySnapshot, Env, Order, OrderStatus, Side, User
from app.schemas import (
    AccountOut,
    CandleOut,
    HoldingOut,
    OrderIn,
    OrderOut,
    OrderPage,
    QuoteOut,
)

router = APIRouter(prefix="/api", tags=["trading"])


# -- 시세 -------------------------------------------------------------------
@router.get("/market/universe")
def universe():
    """데모 유니버스. 실 연동 시에는 증권사 종목 마스터로 대체한다."""
    return [{"symbol": s, "name": n} for s, (n, _) in UNIVERSE.items()]


@router.get("/market/status")
def market_status(
    env: Env = Depends(env_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """지금 시세가 실제 KIS에서 오는지 시뮬레이터에서 오는지.

    앱키 값 자체는 응답에 싣지 않는다.
    """
    info = market.status()
    info["source"] = market_source(db, user.id, env)
    info["account_linked"] = is_live_broker(db, user.id, env)
    return info


@router.get("/market/quote/{symbol}", response_model=QuoteOut)
def quote(
    symbol: str,
    env: Env = Depends(env_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = get_broker(db, user.id, env).get_quote(symbol)
    return QuoteOut(
        symbol=q.symbol, name=q.name, price=q.price, prev_close=q.prev_close,
        change=q.change, change_pct=round(q.change_pct, 2), open=q.open,
        high=q.high, low=q.low, volume=q.volume, ts=q.ts,
    )


@router.get("/market/candles/{symbol}", response_model=list[CandleOut])
def candles(
    symbol: str,
    days: int = Query(default=120, ge=10, le=600),
    env: Env = Depends(env_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return [CandleOut(**c.__dict__) for c in get_broker(db, user.id, env).get_candles(symbol, days)]


# -- 계좌 -------------------------------------------------------------------
@router.get("/account", response_model=AccountOut)
def account(
    env: Env = Depends(env_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    broker = get_broker(db, user.id, env)
    bal = broker.get_balance()
    equity = bal.total_equity

    cash_row = db.query(CashAccount).filter_by(user_id=user.id, env=env).one_or_none()
    deposit = cash_row.deposit_total if cash_row else equity

    prev = (
        db.query(EquitySnapshot)
        .filter(EquitySnapshot.user_id == user.id, EquitySnapshot.env == env)
        .filter(EquitySnapshot.date < date.today())
        .order_by(desc(EquitySnapshot.date))
        .first()
    )
    day_pnl = equity - prev.total_equity if prev else 0.0
    day_pnl_pct = (day_pnl / prev.total_equity * 100) if prev and prev.total_equity else 0.0

    holdings = [
        HoldingOut(
            symbol=h.symbol, name=h.name, quantity=h.quantity, avg_price=round(h.avg_price),
            current_price=h.current_price, market_value=h.market_value,
            unrealized_pnl=round(h.unrealized_pnl), unrealized_pct=round(h.unrealized_pct, 2),
            weight_pct=round(h.market_value / equity * 100, 1) if equity else 0.0,
        )
        for h in bal.holdings
    ]
    return AccountOut(
        env=env.value,
        connected=is_live_broker(db, user.id, env),
        broker=broker.name,
        cash=round(bal.cash),
        holdings_value=round(bal.holdings_value),
        total_equity=round(equity),
        deposit_total=round(deposit),
        total_pnl=round(equity - deposit),
        total_pnl_pct=round((equity / deposit - 1) * 100, 2) if deposit else 0.0,
        day_pnl=round(day_pnl),
        day_pnl_pct=round(day_pnl_pct, 2),
        holdings=holdings,
    )


# -- 주문 -------------------------------------------------------------------
@router.get("/orders", response_model=OrderPage)
def list_orders(
    env: Env = Depends(env_param),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=5, le=100),
    symbol: str | None = None,
    side: str | None = Query(None, pattern="^(buy|sell)$"),
    status_filter: str | None = Query(None, alias="status"),
    source: str | None = Query(None, pattern="^(agent|manual)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Order).filter_by(user_id=user.id, env=env)
    if symbol:
        q = q.filter(Order.symbol == symbol)
    if side:
        q = q.filter(Order.side == Side(side))
    if status_filter:
        q = q.filter(Order.status == OrderStatus(status_filter))
    if source:
        q = q.filter(Order.source == source)

    total = q.count()
    items = (
        q.order_by(desc(Order.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return OrderPage(
        items=[OrderOut.model_validate(o) for o in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/orders", response_model=OrderOut, status_code=201)
def place_order(
    payload: OrderIn,
    env: Env = Depends(env_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    broker = get_broker(db, user.id, env)
    quote = broker.get_quote(payload.symbol)
    res = broker.place_order(
        payload.symbol, payload.side, payload.quantity, payload.price, payload.order_type
    )
    if not res.ok:
        raise HTTPException(400, res.message)

    order = Order(
        user_id=user.id, env=env, broker_order_id=res.broker_order_id,
        symbol=payload.symbol, name=quote.name, side=Side(payload.side),
        order_type=payload.order_type, quantity=payload.quantity,
        price=payload.price or quote.price,
        filled_quantity=res.filled_quantity, filled_price=res.filled_price,
        status=OrderStatus.filled if res.filled_quantity else OrderStatus.pending,
        source="manual", note=res.message,
        filled_at=datetime.now() if res.filled_quantity else None,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return OrderOut.model_validate(order)


@router.delete("/orders/{order_id}", response_model=OrderOut)
def cancel_order(
    order_id: int,
    env: Env = Depends(env_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter_by(id=order_id, user_id=user.id, env=env).one_or_none()
    if order is None:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    if order.status != OrderStatus.pending:
        raise HTTPException(400, "체결이 끝난 주문은 취소할 수 없습니다.")
    if order.broker_order_id:
        get_broker(db, user.id, env).cancel_order(order.broker_order_id)
    order.status = OrderStatus.canceled
    db.commit()
    db.refresh(order)
    return OrderOut.model_validate(order)
