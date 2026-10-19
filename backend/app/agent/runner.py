"""자동매매 실행 루프.

정책이 낸 행동을 그대로 주문으로 보내지 않는다. 사이에 리스크 게이트를 두고
① 거래 시간 ② 신뢰도 임계값 ③ 종목당 비중 한도 ④ 1회 주문금액 한도
⑤ 일일 손실 한도를 순서대로 검사한다. 하나라도 걸리면 신호는 기록하되
주문은 내지 않는다(executed=False).

국내(kr)와 미국(us)은 같은 루프를 쓰되 설정이 시장별로 따로 있다. 미국 정규장은
한국 시간으로 밤을 넘기므로 거래 시간 판정이 자정을 넘는 구간을 지원한다.

시드 앙상블 DQN(논문)은 '목표 주식 비중'을 낸다. 이 경우 주문 수량은
목표 수량 floor(w × 총자산 ÷ 현재가) 와 현재 보유 수량의 차이다
(auto_trading PaperBroker.rebalance 와 같은 식). 논문은 하루 한 번 시가에 리밸런싱하므로
종목마다 하루 한 번만 주문한다. 신뢰도 임계값은 논문 규칙에 없으므로 목표 비중 정책에는
적용하지 않는다(나머지 리스크 게이트는 모두 그대로 적용).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.agent.policy import Observation, get_policy
from app.brokers.factory import get_broker
from app.core.config import settings
from app.core.guard import live_locked
from app.db.session import SessionLocal
from app.models import (
    AgentAction,
    AgentConfig,
    AgentSignal,
    AuditLog,
    EquitySnapshot,
    Env,
    Market,
    Order,
    OrderStatus,
    Side,
    utcnow,
)

OPEN_STATUSES = (OrderStatus.pending, OrderStatus.partial)

log = logging.getLogger("kairo.agent")


class RiskBlocked(Exception):
    """리스크 게이트에 의해 주문이 차단됨."""


# 루프는 몇 초마다 돈다. 장이 닫혔거나 KIS가 쿨다운 중이면 같은 실패가 계속 나는데,
# 그때마다 로그를 남기면 정작 봐야 할 줄이 묻힌다. 같은 (종목, 사유)는 60초에 한 번만.
_QUOTE_ERROR_LOG_SECONDS = 60
_quote_error_seen: dict[tuple[int, str, str], tuple[float, str]] = {}


def _note_quote_failure(user_id: int, market: Market, symbol: str, err: Exception) -> None:
    key = (user_id, market.value, symbol)
    reason = str(err)
    now = time.monotonic()
    seen = _quote_error_seen.get(key)
    if seen and seen[1] == reason and now - seen[0] < _QUOTE_ERROR_LOG_SECONDS:
        return
    _quote_error_seen[key] = (now, reason)
    log.warning("시세 조회 실패 %s [%s]: %s", symbol, market.value, reason)


def _note_quote_success(user_id: int, market: Market, symbol: str) -> None:
    _quote_error_seen.pop((user_id, market.value, symbol), None)


def _now_utc() -> datetime:
    """DB의 created_at 과 비교할 수 있는 naive UTC 시각.

    ORM 기본값이 UTC로 저장되는데 SQLite 컬럼은 타임존을 갖지 않는다. 그래서
    비교 대상도 tzinfo 를 떼어 낸 UTC 여야 한다. datetime.now() (로컬)와 비교하면
    한국에서는 9시간이 어긋난다.
    """
    return utcnow().replace(tzinfo=None)


def _today_start_utc() -> datetime:
    """오늘(서버 로컬 기준) 00:00 을 naive UTC 로.

    일일 한도는 사람이 보는 하루와 같아야 하므로 UTC 자정이 아니라 로컬 자정에서 끊는다.
    """
    local_midnight = (
        datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    )
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


# 목표 비중 매수 수량을 정할 때 얹는 매수 비용 여유분. 국내 위탁수수료(0.015% 안팎)보다
# 넉넉하게 잡아, 예수금이 수수료만큼 모자라 주문이 거부되는 일을 막는다.
BUY_COST_BUFFER = 0.0005

# 목표 비중 정책의 '오늘 결정 완료' 표시. (user, env, market, symbol) -> 날짜.
# 목표 수량과 보유 수량이 같아 주문할 것이 없었던 날도 여기에 남겨, 장중 가격 변화로
# 목표 수량이 1주씩 흔들릴 때마다 사고팔지 않게 한다. 주문을 낸 날은 DB 로도 확인한다.
_rebalanced_on: dict[tuple[int, str, str, str], date] = {}


def _within_hours(cfg: AgentConfig) -> bool:
    """거래 시간 판정. 미국장처럼 자정을 넘는 구간(22:35~04:55)도 지원한다."""
    now = datetime.now().strftime("%H:%M")
    start, end = cfg.trading_start, cfg.trading_end
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def _daily_pnl_pct(
    db: Session, user_id: int, env: Env, market: Market, equity: float
) -> float:
    prev = (
        db.query(EquitySnapshot)
        .filter(
            EquitySnapshot.user_id == user_id,
            EquitySnapshot.env == env,
            EquitySnapshot.market == market,
        )
        .filter(EquitySnapshot.date < date.today())
        .order_by(EquitySnapshot.date.desc())
        .first()
    )
    if not prev or not prev.total_equity:
        return 0.0
    return (equity / prev.total_equity - 1) * 100


def step_once(
    db: Session,
    user_id: int,
    env: Env,
    market: Market = Market.kr,
    dry_run: bool = False,
) -> list[dict]:
    """해당 시장 유니버스 전 종목에 대해 정책을 1회 실행한다."""
    cfg = (
        db.query(AgentConfig).filter_by(user_id=user_id, env=env, market=market).one_or_none()
    )
    if cfg is None:
        cfg = AgentConfig(user_id=user_id, env=env, market=market)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)

    broker = get_broker(db, user_id, env, market)
    balance = broker.get_balance()
    equity = balance.total_equity or 1.0
    held = {h.symbol: h for h in balance.holdings}

    results: list[dict] = []
    # 미국 종목코드는 대문자로 정규화한다(aapl 로 넣어도 동작하도록).
    symbols = [
        (s.strip().upper() if market == Market.us else s.strip())
        for s in cfg.universe.split(",")
        if s.strip()
    ]

    policy = get_policy(cfg.model_name)
    lookback = getattr(policy, "candle_lookback", 90)

    for symbol in symbols:
        try:
            candles = broker.get_candles(symbol, lookback)
            quote = broker.get_quote(symbol)
        except Exception as e:  # noqa: BLE001
            _note_quote_failure(user_id, market, symbol, e)
            continue
        _note_quote_success(user_id, market, symbol)

        h = held.get(symbol)
        obs = Observation(
            symbol=symbol,
            candles=candles,
            price=quote.price,
            cash_ratio=balance.cash / equity,
            position_ratio=(h.market_value / equity) if h else 0.0,
            unrealized_pct=h.unrealized_pct if h else 0.0,
            quantity=h.quantity if h else 0,
            equity=equity,
        )

        out = policy.act(obs)
        weight_policy = out.target_weight is not None
        day_key = (user_id, env.value, market.value, quote.symbol)
        signal = AgentSignal(
            user_id=user_id,
            env=env,
            market=market,
            symbol=quote.symbol,
            action=AgentAction(out.action),
            confidence=out.confidence,
            q_buy=out.q_values.get("buy", 0.0),
            q_hold=out.q_values.get("hold", 0.0),
            q_sell=out.q_values.get("sell", 0.0),
            price=quote.price,
            reason=out.reason,
            executed=False,
        )

        blocked: str | None = None
        try:
            if dry_run:
                raise RiskBlocked("미리보기 실행")
            if not cfg.enabled:
                raise RiskBlocked("자동매매가 꺼져 있음")
            # 라우터에서 이미 막지만 여기서도 본다. 잠금 이전에 켜 둔 설정이
            # 남아 있거나 서버 설정이 도중에 바뀌었을 때를 대비한 두 번째 문이다.
            if live_locked(env):
                raise RiskBlocked("실계좌 주문 잠금 (ALLOW_LIVE_TRADING=false)")
            if not cfg.risk_ack_at:
                raise RiskBlocked("리스크 한도 확인 전")
            if weight_policy and _rebalanced_on.get(day_key) == date.today():
                raise RiskBlocked("오늘 리밸런싱 완료")
            if not weight_policy and out.action == "hold":
                raise RiskBlocked("관망")
            if not _within_hours(cfg):
                raise RiskBlocked(f"거래 시간 밖 ({cfg.trading_start}~{cfg.trading_end})")
            if not weight_policy and out.confidence < cfg.confidence_threshold:
                raise RiskBlocked(
                    f"신뢰도 {out.confidence:.2f} < 임계값 {cfg.confidence_threshold:.2f}"
                )
            if _daily_pnl_pct(db, user_id, env, market, equity) <= -cfg.daily_loss_limit_pct:
                raise RiskBlocked(f"일일 손실 한도 {cfg.daily_loss_limit_pct}% 도달")

            # ── 같은 주문이 반복해서 나가는 것을 막는다 ──────────────────
            #
            # 규칙 기반 정책은 조건이 유지되는 한 매 틱 같은 신호를 낸다. 아래 세 개가
            # 없으면 루프 주기(기본 5초)마다 같은 매수가 계속 나간다. 실제로 10분 만에
            # 같은 주문 71건이 쌓인 적이 있다. 실계좌였으면 사고다.
            base = db.query(Order).filter_by(
                user_id=user_id, env=env, market=market, symbol=quote.symbol
            )

            open_count = base.filter(Order.status.in_(OPEN_STATUSES)).count()
            if open_count:
                raise RiskBlocked(f"{quote.symbol} 미체결 주문 {open_count}건이 남아 있음")

            if weight_policy:
                done_today = base.filter(
                    Order.source == "agent",
                    Order.status != OrderStatus.rejected,
                    Order.created_at >= _today_start_utc(),
                ).count()
                if done_today:
                    _rebalanced_on[day_key] = date.today()
                    raise RiskBlocked("오늘 리밸런싱 완료")

            if cfg.order_cooldown_seconds > 0:
                since = _now_utc() - timedelta(seconds=cfg.order_cooldown_seconds)
                if base.filter(Order.created_at >= since).count():
                    raise RiskBlocked(
                        f"직전 주문 이후 {cfg.order_cooldown_seconds}초 재주문 대기 중"
                    )

            today_orders = (
                db.query(Order)
                .filter_by(user_id=user_id, env=env, market=market, source="agent")
                .filter(Order.created_at >= _today_start_utc())
                .count()
            )
            if today_orders >= cfg.max_daily_orders:
                raise RiskBlocked(f"일일 주문 건수 한도 {cfg.max_daily_orders}건 도달")

            if weight_policy:
                if quote.price <= 0:
                    raise RiskBlocked("현재가를 알 수 없음")
                held_qty = h.quantity if h else 0
                # 목표 수량: floor(w × 총자산 ÷ 가격). 종목당 최대 비중 한도로 한 번 더 자른다.
                target_qty = int((out.target_weight * equity) // quote.price)
                cap_qty = int((equity * cfg.max_position_pct / 100) // quote.price)
                target_qty = min(target_qty, cap_qty)
                change = target_qty - held_qty
                if change == 0:
                    out.action = "hold"
                    signal.action = AgentAction.hold
                    _rebalanced_on[day_key] = date.today()
                    raise RiskBlocked(
                        f"목표 비중 {out.target_weight:.0%} → 목표 {target_qty}주 = 보유 {held_qty}주"
                    )
                if change > 0:
                    # 예수금 전부로 사는 날(목표 100%)에도 수수료 때문에 거부되지 않게
                    # PaperBroker 처럼 수수료를 얹은 단가로 살 수 있는 수량까지만 낸다.
                    budget = min(cfg.max_order_amount, balance.cash)
                    unit_cost = quote.price * (1 + BUY_COST_BUFFER)
                    qty = min(change, int(budget // unit_cost))
                    if qty < 1:
                        raise RiskBlocked("1회 주문금액 한도 또는 예수금 부족")
                    side = Side.buy
                else:
                    # 비중 축소는 위험을 줄이는 방향이라 1회 주문금액으로 자르지 않는다.
                    qty = min(-change, held_qty)
                    side = Side.sell
                out.action = side.value
                signal.action = AgentAction(side.value)
            elif out.action == "buy":
                room = equity * (cfg.max_position_pct / 100) - (h.market_value if h else 0)
                budget = min(room, cfg.max_order_amount, balance.cash)
                qty = int(budget // quote.price)
                if qty < 1:
                    raise RiskBlocked("비중 한도 또는 예수금 부족")
                side = Side.buy
            else:
                if not h or h.quantity < 1:
                    raise RiskBlocked("매도할 보유 수량 없음")
                qty = h.quantity
                side = Side.sell

            res = broker.place_order(quote.symbol, side.value, qty, quote.price, "limit")

            # 전송이 실패했으면 '접수됨(pending)' 으로 남기지 않는다. 증권사에 없는
            # 주문이 미체결인 척 쌓이면 거래 내역도 체결 폴링도 전부 거짓이 된다.
            if res.ok:
                status = OrderStatus.filled if res.filled_quantity else OrderStatus.pending
                note = f"{out.reason} (신뢰도 {out.confidence:.2f})"
            else:
                status = OrderStatus.rejected
                note = f"주문 거부: {res.message}"

            db.add(
                Order(
                    user_id=user_id,
                    env=env,
                    market=market,
                    broker_order_id=res.broker_order_id,
                    symbol=quote.symbol,
                    name=quote.name,
                    side=side,
                    order_type="limit",
                    quantity=qty,
                    price=quote.price,
                    filled_quantity=res.filled_quantity,
                    filled_price=res.filled_price,
                    fee=res.fee,
                    tax=res.tax,
                    realized_pnl=res.realized_pnl,
                    status=status,
                    source="agent",
                    note=note,
                    filled_at=_now_utc() if res.filled_quantity else None,
                )
            )
            signal.executed = res.ok
            if res.ok and weight_policy:
                _rebalanced_on[day_key] = date.today()
            if not res.ok:
                blocked = res.message
        except RiskBlocked as e:
            blocked = str(e)

        if blocked:
            signal.reason = f"{signal.reason} — {blocked}" if signal.reason else blocked

        db.add(signal)
        results.append(
            {
                "symbol": quote.symbol,
                "market": market.value,
                "currency": quote.currency,
                "name": quote.name,
                "action": out.action,
                "target_weight": out.target_weight,
                "confidence": out.confidence,
                "q_values": out.q_values,
                "price": quote.price,
                "executed": signal.executed,
                "reason": signal.reason,
            }
        )

    db.commit()
    return results


# --------------------------------------------------------------------------
# 백그라운드 루프
# --------------------------------------------------------------------------
class AgentLoop:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="agent-loop")
        self._thread.start()
        log.info("자동매매 루프를 시작했습니다 (주기 %ss).", settings.agent_tick_seconds)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(settings.agent_tick_seconds):
            db = SessionLocal()
            try:
                for cfg in db.query(AgentConfig).filter_by(enabled=True).all():
                    # 잠긴 환경에서 켜져 있는 설정은 매 틱 헛돌 뿐이다. 꺼 두고 넘어간다.
                    if live_locked(cfg.env):
                        cfg.enabled = False
                        db.add(
                            AuditLog(
                                user_id=cfg.user_id,
                                event="agent.auto_off",
                                detail=f"{cfg.env.value}/{cfg.market.value}:live_locked",
                            )
                        )
                        db.commit()
                        log.warning(
                            "실계좌 잠금 상태라 자동매매를 껐습니다 user=%s market=%s",
                            cfg.user_id,
                            cfg.market,
                        )
                        continue
                    try:
                        step_once(db, cfg.user_id, cfg.env, cfg.market)
                    except Exception:  # noqa: BLE001
                        log.exception(
                            "에이전트 스텝 실패 user=%s env=%s market=%s",
                            cfg.user_id,
                            cfg.env,
                            cfg.market,
                        )
            finally:
                db.close()


agent_loop = AgentLoop()
