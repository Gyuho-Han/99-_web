"""자격증명 유무와 시장에 따라 어댑터를 고른다.

우선순위
1. 사용자가 /keys 화면에서 등록한 (env, market) 자격증명 → 실주문 어댑터
2. .env 의 서버 공용 KIS 앱키                            → HybridBroker (실시세 + 모의체결)
3. 아무것도 없음                                         → MockBroker (전부 시뮬레이터)

국내는 KISBroker, 미국은 KISOverseasBroker를 쓴다. 앱키는 같은 것을 쓰지만
엔드포인트와 계좌번호가 달라서 어댑터가 갈린다.

시세는 계좌와 따로 본다
----------------------
1번(개인 자격증명)이라도 .env 공용 앱키가 있으면 **시세만** 공용 소스에서 가져오도록
MarketDataBroker 로 감싼다. KIS 모의투자 도메인이 시세조회를 제대로 지원하지 않아서,
모의투자 계좌를 붙이는 순간 현재가·일봉이 500으로 깨지기 때문이다. 자세한 이유는
brokers/overlay.py 를 보라.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.brokers import market as market_source
from app.brokers.base import BrokerAdapter
from app.brokers.hybrid import HybridBroker
from app.brokers.kis import KISBroker
from app.brokers.kis_overseas import KISOverseasBroker
from app.brokers.mock import MockBroker
from app.brokers.overlay import MarketDataBroker
from app.core.security import decrypt_secret
from app.models import BrokerCredential, Env, Market


def _market_key(market: Market) -> str:
    return market_source.US if market == Market.us else market_source.KR


def _fallback(db: Session, user_id: int, env: Env, market: Market) -> BrokerAdapter:
    """개인 자격증명이 없을 때. .env 키가 있으면 시세만 실제로 붙인다."""
    if market_source.is_enabled(_market_key(market)):
        return HybridBroker(db, user_id, env, market)
    return MockBroker(db, user_id, env, market)


def get_broker(
    db: Session, user_id: int, env: Env, market: Market = Market.kr, force_mock: bool = False
) -> BrokerAdapter:
    if force_mock:
        return _fallback(db, user_id, env, market)

    cred = (
        db.query(BrokerCredential)
        .filter_by(user_id=user_id, env=env, market=market, is_active=True)
        .one_or_none()
    )
    if cred is None:
        return _fallback(db, user_id, env, market)

    if cred.broker == "kis":
        cls = KISOverseasBroker if market == Market.us else KISBroker
        account = cls(
            app_key=decrypt_secret(cred.app_key_enc),
            app_secret=decrypt_secret(cred.app_secret_enc),
            account_no=decrypt_secret(cred.account_no_enc),
            is_paper=(env == Env.paper),
        )
        # 공용 실시세가 있으면 시세만 그쪽에서 받는다. 없으면 계좌 어댑터가 다 한다.
        if market_source.is_enabled(_market_key(market)):
            return MarketDataBroker(account, market)
        return account

    return _fallback(db, user_id, env, market)


def is_live_broker(db: Session, user_id: int, env: Env, market: Market = Market.kr) -> bool:
    """실제 증권사 계좌(주문까지)가 연결되어 있는지 여부."""
    return (
        db.query(BrokerCredential)
        .filter_by(user_id=user_id, env=env, market=market, is_active=True)
        .count()
        > 0
    )


def market_source_of(db: Session, user_id: int, env: Env, market: Market = Market.kr) -> str:
    """지금 시세가 어디서 오는지: 'kis' | 'simulator'.

    계좌 연결 여부보다 먼저 공용 소스를 본다. 계좌를 붙여도 시세는 공용 소스에서
    오기 때문이다(overlay.py). 쿨다운 중이면 실시세가 나가지 않으므로 그렇게 보고한다.
    화면 배지가 '실시세'라고 떠 있는데 값은 그렇지 않은 상황을 막는 것이 목적이다.
    """
    key = _market_key(market)
    if market_source.is_enabled(key):
        return "simulator" if market_source.status(key)["degraded"] else "kis"
    # 공용 앱키가 없으면 개인 자격증명 어댑터가 시세까지 직접 받아 온다.
    return "kis" if is_live_broker(db, user_id, env, market) else "simulator"
