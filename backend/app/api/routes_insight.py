"""수익 분석 및 에이전트 제어."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.agent.policy import list_policies
from app.agent.runner import step_once
from app.api.deps import current_user, env_param, market_param
from app.brokers.factory import is_live_broker
from app.core.guard import LIVE_LOCK_MESSAGE, live_locked
from app.db.session import get_db
from app.models import (
    AgentConfig,
    AgentSignal,
    AuditLog,
    EquitySnapshot,
    Env,
    Market,
    Order,
    OrderStatus,
    User,
    utcnow,
)
from app.schemas import (
    AgentConfigIn,
    AgentConfigOut,
    EquityPoint,
    PerformanceOut,
    SignalOut,
)
from app.services import metrics as M

router = APIRouter(prefix="/api", tags=["insight"])


# -- 성과 -------------------------------------------------------------------
@router.get("/performance", response_model=PerformanceOut)
def performance(
    env: Env = Depends(env_param),
    mkt: Market = Depends(market_param),
    days: int = Query(default=180, ge=7, le=1000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    since = date.today() - timedelta(days=days)
    rows = (
        db.query(EquitySnapshot)
        .filter(
            EquitySnapshot.user_id == user.id,
            EquitySnapshot.env == env,
            EquitySnapshot.market == mkt,
        )
        .filter(EquitySnapshot.date >= since)
        .order_by(asc(EquitySnapshot.date))
        .all()
    )
    dates = [r.date.isoformat() for r in rows]
    equity = [r.total_equity for r in rows]
    bench = [r.benchmark_value for r in rows]

    pnls = [
        o.realized_pnl
        for o in db.query(Order)
        .filter_by(user_id=user.id, env=env, market=mkt, status=OrderStatus.filled)
        .all()
        if o.realized_pnl
    ]

    dd = M.drawdown_series(equity)
    return PerformanceOut(
        env=env.value,
        market=mkt.value,
        currency="USD" if mkt == Market.us else "KRW",
        metrics=M.compute(equity, pnls).dict(),
        benchmark_metrics=M.compute(bench).dict(),
        curve=[
            EquityPoint(
                date=d,
                equity=round(e, 2 if mkt == Market.us else 0),
                benchmark=round(b, 2 if mkt == Market.us else 0),
                drawdown=round(x, 2),
            )
            for d, e, b, x in zip(dates, equity, bench, dd)
        ],
        monthly=M.monthly_returns(dates, equity),
    )


# -- 에이전트 ---------------------------------------------------------------
DEFAULT_UNIVERSE = {"kr": "005930,000660,035420", "us": "AAPL,NVDA,MSFT"}
# 1회 최대 주문금액의 기본값. 통화가 다르므로 시장마다 따로 둔다.
# (이 값이 없으면 미국 설정도 2,000,000 이 들어가 사실상 한도가 없는 것과 같았다)
DEFAULT_MAX_ORDER = {"kr": 2_000_000.0, "us": 2_000.0}


def _cfg(db: Session, user_id: int, env: Env, market: Market) -> AgentConfig:
    cfg = (
        db.query(AgentConfig).filter_by(user_id=user_id, env=env, market=market).one_or_none()
    )
    if cfg is None:
        cfg = AgentConfig(
            user_id=user_id,
            env=env,
            market=market,
            universe=DEFAULT_UNIVERSE[market.value],
            max_order_amount=DEFAULT_MAX_ORDER[market.value],
            # 미국 정규장은 한국 시간으로 밤이라 기본 거래시간을 서머타임 기준으로 잡는다.
            trading_start="22:35" if market == Market.us else "09:05",
            trading_end="04:55" if market == Market.us else "15:15",
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _cfg_out(cfg: AgentConfig, db: Session, user_id: int) -> AgentConfigOut:
    return AgentConfigOut(
        env=cfg.env.value,
        market=cfg.market.value,
        enabled=cfg.enabled,
        risk_ack_at=cfg.risk_ack_at,
        live_locked=live_locked(cfg.env),
        account_linked=is_live_broker(db, user_id, cfg.env, cfg.market),
        model_name=cfg.model_name,
        available_models=list_policies(),
        universe=[s.strip() for s in cfg.universe.split(",") if s.strip()],
        max_position_pct=cfg.max_position_pct,
        max_order_amount=cfg.max_order_amount,
        daily_loss_limit_pct=cfg.daily_loss_limit_pct,
        confidence_threshold=cfg.confidence_threshold,
        order_cooldown_seconds=cfg.order_cooldown_seconds,
        max_daily_orders=cfg.max_daily_orders,
        trading_start=cfg.trading_start,
        trading_end=cfg.trading_end,
        updated_at=cfg.updated_at,
    )


@router.get("/agent/config", response_model=AgentConfigOut)
def get_agent_config(
    env: Env = Depends(env_param),
    mkt: Market = Depends(market_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return _cfg_out(_cfg(db, user.id, env, mkt), db, user.id)


@router.patch("/agent/config", response_model=AgentConfigOut)
def update_agent_config(
    payload: AgentConfigIn,
    env: Env = Depends(env_param),
    mkt: Market = Depends(market_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    cfg = _cfg(db, user.id, env, mkt)
    data = payload.model_dump(exclude_none=True)

    # 리스크 한도 확인. 켤 때만 본다. 끄는 것은 언제나 막지 않는다.
    turning_on = data.get("enabled") is True and not cfg.enabled
    if turning_on:
        if live_locked(env):
            raise HTTPException(423, LIVE_LOCK_MESSAGE)
        if not (data.pop("risk_ack", False) or cfg.risk_ack_at):
            raise HTTPException(
                428,
                "자동매매를 켜기 전에 리스크 한도를 확인해야 합니다. "
                "에이전트 화면의 가동 전 확인 절차를 먼저 마치세요.",
            )
        cfg.risk_ack_at = utcnow()
    else:
        # 켜는 상황이 아니면 확인 플래그는 의미가 없다. 설정값으로 새어 들어가지 않게 버린다.
        data.pop("risk_ack", None)

    if "enabled" in data and data["enabled"] != cfg.enabled:
        db.add(
            AuditLog(
                user_id=user.id,
                event="agent.toggle",
                detail=f"{env.value}/{mkt.value}:{'on' if data['enabled'] else 'off'}",
            )
        )
    for k, v in data.items():
        setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return _cfg_out(cfg, db, user.id)


@router.get("/agent/signals", response_model=list[SignalOut])
def signals(
    env: Env = Depends(env_param),
    mkt: Market = Depends(market_param),
    limit: int = Query(default=60, ge=1, le=300),
    symbol: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AgentSignal).filter_by(user_id=user.id, env=env, market=mkt)
    if symbol:
        q = q.filter(AgentSignal.symbol == symbol)
    rows = q.order_by(desc(AgentSignal.created_at)).limit(limit).all()
    return [SignalOut.model_validate(r) for r in rows]


@router.post("/agent/step")
def agent_step(
    env: Env = Depends(env_param),
    mkt: Market = Depends(market_param),
    dry_run: bool = Query(default=True),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """정책을 1회 수동 실행한다. dry_run=true면 신호만 남기고 주문은 내지 않는다."""
    if not dry_run and live_locked(env):
        raise HTTPException(423, LIVE_LOCK_MESSAGE)
    return {
        "results": step_once(db, user.id, env, mkt, dry_run=dry_run),
        "account_linked": is_live_broker(db, user.id, env, mkt),
    }
