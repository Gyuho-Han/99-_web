"""미체결 주문 체결 반영.

증권사 주문 API는 "접수했다"까지만 알려 준다. 그래서 실계좌로 낸 주문은 DB에
`pending` 으로 남고, 실제로 체결됐는지는 체결조회를 따로 불러야 알 수 있다.
이 모듈이 그 간극을 메운다.

  1. 아직 끝나지 않은 주문(pending·partial)을 (사용자, 환경, 시장)별로 모은다
  2. 그 조합의 어댑터에 주문번호를 한꺼번에 넘겨 체결 상태를 받는다
  3. 체결 수량이 늘었으면 주문 행을 갱신한다

시뮬레이터(Mock·Hybrid)는 주문을 내는 즉시 체결시키므로 미체결이라는 상태가
없다. `BrokerAdapter.get_fills` 의 기본 구현이 빈 dict를 돌려주므로 여기서
따로 갈라 볼 필요가 없다.

한계: 수수료·세금과 실현손익은 채우지 않는다. KIS 체결조회 응답만으로는 매도
시점의 취득단가를 알 수 없고, 실계좌의 취득단가는 우리 DB가 아니라 증권사 잔고가
가지고 있기 때문이다. 어림값을 적어 넣으면 수익 분석 화면이 조용히 틀린 숫자를
보여 주게 되므로, 채우지 않고 비워 둔다.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.brokers.factory import get_broker, is_live_broker
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Env, Market, Order, OrderStatus, utcnow

log = logging.getLogger("kairo.fills")

OPEN_STATUSES = (OrderStatus.pending, OrderStatus.partial)


def _apply(order: Order, fill) -> bool:
    """체결 결과를 주문 행에 반영한다. 실제로 바뀐 것이 있으면 True."""
    # 한 주도 못 채우고 취소된 주문.
    if fill.canceled and fill.filled_quantity <= 0:
        if order.status == OrderStatus.canceled:
            return False
        order.status = OrderStatus.canceled
        order.note = (order.note or "").strip() or "증권사에서 취소된 주문입니다."
        return True

    filled = min(int(fill.filled_quantity), order.quantity)
    if filled <= order.filled_quantity and not fill.canceled:
        return False   # 지난번 조회 이후 늘어난 것이 없다

    order.filled_quantity = filled
    if fill.filled_price > 0:
        order.filled_price = fill.filled_price

    if filled >= order.quantity:
        order.status = OrderStatus.filled
        order.filled_at = order.filled_at or utcnow()
    elif fill.canceled:
        # 일부만 체결된 채 취소됐다. 남은 수량은 더 이상 채워지지 않는다.
        order.status = OrderStatus.partial
        order.note = "부분 체결 후 취소되었습니다."
    else:
        order.status = OrderStatus.partial
    return True


def sync_pending_orders(db: Session) -> int:
    """열려 있는 주문의 체결 상태를 증권사에서 읽어 갱신한다. 갱신한 주문 수를 돌려준다."""
    if settings.fill_poll_max_age_days > 0:
        cutoff = datetime.now() - timedelta(days=settings.fill_poll_max_age_days)
    else:
        cutoff = datetime.min

    rows = (
        db.query(Order)
        .filter(Order.status.in_(OPEN_STATUSES))
        .filter(Order.broker_order_id.isnot(None))
        .filter(Order.created_at >= cutoff)
        .all()
    )
    if not rows:
        return 0

    groups: dict[tuple[int, Env, Market], list[Order]] = {}
    for o in rows:
        groups.setdefault((o.user_id, o.env, o.market), []).append(o)

    changed = 0
    for (user_id, env, market), orders in groups.items():
        # 개인 자격증명이 없는 조합은 시뮬레이터가 처리한 주문이라 조회할 것이 없다.
        if not is_live_broker(db, user_id, env, market):
            continue
        ids = [o.broker_order_id for o in orders if o.broker_order_id]
        try:
            fills = get_broker(db, user_id, env, market).get_fills(ids)
        except Exception as e:  # noqa: BLE001
            # 조회 실패로 루프가 멈추면 다른 사용자의 주문까지 못 따라간다.
            log.warning("체결 조회 실패 user=%s env=%s market=%s: %s", user_id, env, market, e)
            continue

        for o in orders:
            fill = fills.get(o.broker_order_id)
            if fill is None:
                continue      # 조회 구간 밖이거나 아직 목록에 안 올라온 주문
            if _apply(o, fill):
                changed += 1

    if changed:
        db.commit()
        log.info("체결 상태를 갱신했습니다: %d건", changed)
    return changed


class FillPoller:
    """주기적으로 미체결 주문을 따라가는 백그라운드 스레드."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if settings.fill_poll_seconds <= 0:
            log.info("체결 폴링이 꺼져 있습니다 (FILL_POLL_SECONDS=0).")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="fill-poller")
        self._thread.start()
        log.info("체결 폴링을 시작했습니다 (주기 %ss).", settings.fill_poll_seconds)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(settings.fill_poll_seconds):
            db = SessionLocal()
            try:
                sync_pending_orders(db)
            except Exception:  # noqa: BLE001
                log.exception("체결 폴링 중 오류")
            finally:
                db.close()


fill_poller = FillPoller()
