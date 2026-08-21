"""자격증명 유무에 따라 어댑터를 고른다.

우선순위
1. 사용자가 /keys 화면에서 등록한 증권사 자격증명 → 해당 증권사 어댑터 (실주문)
2. .env 의 서버 공용 KIS 앱키       → HybridBroker (실시세 + 모의체결)
3. 아무것도 없음                     → MockBroker (전부 시뮬레이터)
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.brokers import market
from app.brokers.base import BrokerAdapter
from app.brokers.hybrid import HybridBroker
from app.brokers.kis import KISBroker
from app.brokers.mock import MockBroker
from app.core.security import decrypt_secret
from app.models import BrokerCredential, Env


def _fallback(db: Session, user_id: int, env: Env) -> BrokerAdapter:
    """개인 자격증명이 없을 때. .env 키가 있으면 시세만 실제로 붙인다."""
    if market.is_enabled():
        return HybridBroker(db, user_id, env)
    return MockBroker(db, user_id, env)


def get_broker(db: Session, user_id: int, env: Env, force_mock: bool = False) -> BrokerAdapter:
    if force_mock:
        return _fallback(db, user_id, env)

    cred = (
        db.query(BrokerCredential)
        .filter_by(user_id=user_id, env=env, is_active=True)
        .one_or_none()
    )
    if cred is None:
        return _fallback(db, user_id, env)

    if cred.broker == "kis":
        return KISBroker(
            app_key=decrypt_secret(cred.app_key_enc),
            app_secret=decrypt_secret(cred.app_secret_enc),
            account_no=decrypt_secret(cred.account_no_enc),
            is_paper=(env == Env.paper),
        )

    return _fallback(db, user_id, env)


def is_live_broker(db: Session, user_id: int, env: Env) -> bool:
    """실제 증권사 계좌(주문까지)가 연결되어 있는지 여부."""
    return (
        db.query(BrokerCredential).filter_by(user_id=user_id, env=env, is_active=True).count() > 0
    )


def market_source(db: Session, user_id: int, env: Env) -> str:
    """지금 시세가 어디서 오는지: 'kis' | 'simulator'."""
    if is_live_broker(db, user_id, env):
        return "kis"
    return "kis" if market.is_enabled() else "simulator"
