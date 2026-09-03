"""증권계좌 연결 상태와 비상정지.

/keys 화면은 "앱키를 어디에 넣는가"만 알려 주면 부족하다. 키를 넣은 다음
무엇을 더 해야 실제로 주문이 나가는지가 사용자 입장에서는 더 궁금하다.
그래서 연결에 필요한 단계를 서버가 직접 판정해서 돌려준다. 화면은 그것을
그대로 그리기만 하면 되고, 판정 규칙이 한 곳에만 있게 된다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user, env_param, market_param
from app.brokers.factory import get_broker, is_live_broker, market_source_of
from app.core.guard import live_locked, live_trading_allowed, lock_reason
from app.db.session import get_db
from app.models import (
    AgentConfig,
    AuditLog,
    BrokerCredential,
    Env,
    Market,
    Order,
    OrderStatus,
    User,
)

router = APIRouter(prefix="/api", tags=["connection"])

OPEN_STATUSES = (OrderStatus.pending, OrderStatus.partial)


def _step(key: str, title: str, done: bool, detail: str, blocked: str | None = None) -> dict:
    return {"key": key, "title": title, "done": done, "detail": detail, "blocked": blocked}


@router.get("/connection/status")
def connection_status(
    env: Env = Depends(env_param),
    mkt: Market = Depends(market_param),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """지금 이 (환경, 시장) 조합이 실거래까지 몇 단계 남았는지."""
    cred = (
        db.query(BrokerCredential)
        .filter_by(user_id=user.id, broker="kis", env=env, market=mkt)
        .one_or_none()
    )
    cfg = (
        db.query(AgentConfig).filter_by(user_id=user.id, env=env, market=mkt).one_or_none()
    )
    locked = live_locked(env)
    시장 = "미국주식" if mkt == Market.us else "국내주식"
    계좌 = "모의투자" if env == Env.paper else "실계좌"

    verified = bool(cred and cred.last_verified_at)
    steps = [
        _step(
            "register",
            "앱키와 계좌번호 등록",
            bool(cred),
            f"KIS 개발자센터에서 발급받은 {계좌} 앱키를 아래에 넣습니다. "
            "App Secret과 계좌번호는 암호화해서 보관합니다.",
        ),
        _step(
            "verify",
            "연결 테스트 통과",
            verified,
            "접근토큰 발급과 잔고 조회를 실제로 한 번 해 봅니다. "
            "여기서 실패하면 주문은 나가지 않습니다.",
        ),
        _step(
            "risk",
            "리스크 한도 확인",
            bool(cfg and cfg.risk_ack_at),
            "1회 주문금액·종목당 비중·일일 손실 한도·거래시간을 확인합니다. "
            "확인 전에는 자동매매를 켤 수 없습니다.",
        ),
        _step(
            "run",
            "자동매매 가동",
            bool(cfg and cfg.enabled),
            f"{시장} {계좌}에서 정책이 낸 신호가 리스크 게이트를 통과하면 주문으로 나갑니다.",
            blocked=lock_reason(env),
        ),
    ]

    # 전체 조합 현황. 상단 시장·환경 토글을 누르지 않고도 어디가 비어 있는지 보인다.
    matrix = []
    for m in (Market.kr, Market.us):
        for e in (Env.paper, Env.live):
            c = (
                db.query(BrokerCredential)
                .filter_by(user_id=user.id, broker="kis", env=e, market=m)
                .one_or_none()
            )
            g = db.query(AgentConfig).filter_by(user_id=user.id, env=e, market=m).one_or_none()
            matrix.append(
                {
                    "market": m.value,
                    "env": e.value,
                    "registered": bool(c),
                    "verified": bool(c and c.last_verified_at),
                    "agent_enabled": bool(g and g.enabled),
                    "locked": live_locked(e),
                }
            )

    return {
        "env": env.value,
        "market": mkt.value,
        "broker": "kis",
        "steps": steps,
        "matrix": matrix,
        "account_linked": is_live_broker(db, user.id, env, mkt),
        "market_source": market_source_of(db, user.id, env, mkt),
        "live_trading_allowed": live_trading_allowed(),
        "locked": locked,
        "lock_reason": lock_reason(env),
        # 마지막 단계까지 갈 수 있는 상태인가. 잠겨 있으면 아무리 채워도 False.
        "ready": verified and not locked,
        "open_orders": (
            db.query(Order)
            .filter_by(user_id=user.id, env=env, market=mkt)
            .filter(Order.status.in_(OPEN_STATUSES))
            .count()
        ),
    }


@router.post("/agent/panic")
def panic(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """비상정지. 모든 환경·시장의 자동매매를 끄고 미체결 주문 취소를 시도한다.

    환경이나 시장을 가리지 않는다. 급할 때 토글을 네 번 누르게 하면 안 된다.
    """
    disabled = 0
    for cfg in db.query(AgentConfig).filter_by(user_id=user.id, enabled=True).all():
        cfg.enabled = False
        disabled += 1
        db.add(
            AuditLog(
                user_id=user.id,
                event="agent.panic",
                detail=f"{cfg.env.value}/{cfg.market.value}:off",
            )
        )

    canceled, failed = 0, 0
    open_orders = (
        db.query(Order)
        .filter_by(user_id=user.id)
        .filter(Order.status.in_(OPEN_STATUSES))
        .all()
    )
    # 어댑터는 (환경, 시장)마다 하나면 된다. 주문마다 새로 만들면 토큰 조회가 낭비된다.
    brokers: dict[tuple[Env, Market], object] = {}
    for o in open_orders:
        if not o.broker_order_id:
            # 시뮬레이터 주문. 증권사에 보낼 것이 없으므로 DB에서만 정리한다.
            o.status = OrderStatus.canceled
            canceled += 1
            continue
        key = (o.env, o.market)
        if key not in brokers:
            brokers[key] = get_broker(db, user.id, o.env, o.market)
        try:
            res = brokers[key].cancel_order(o.broker_order_id)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        if res.ok:
            o.status = OrderStatus.canceled
            canceled += 1
        else:
            # 이미 체결됐을 수도 있다. 임의로 취소 처리하면 화면이 거짓을 말하게 되므로
            # 상태는 그대로 두고 사유만 남긴다.
            failed += 1
            o.note = res.message or "취소가 거부되었습니다."

    db.add(
        AuditLog(
            user_id=user.id,
            event="agent.panic.summary",
            detail=f"disabled={disabled} canceled={canceled} failed={failed}",
        )
    )
    db.commit()

    parts = [f"자동매매 {disabled}건을 껐습니다."]
    if canceled:
        parts.append(f"미체결 주문 {canceled}건을 취소했습니다.")
    if failed:
        parts.append(f"{failed}건은 취소되지 않았습니다. 증권사 화면에서 직접 확인하세요.")
    return {
        "disabled": disabled,
        "canceled": canceled,
        "failed": failed,
        "at": datetime.now(),
        "message": " ".join(parts),
    }
