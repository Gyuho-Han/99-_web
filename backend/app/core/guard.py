"""실거래 게이트.

정책이 아무리 자신 있게 매수를 외쳐도, 실계좌에서 돈이 나가려면 서버 환경변수
`ALLOW_LIVE_TRADING=true` 를 지나야 한다. 프런트엔드 조작이나 API 직접 호출로는
풀 수 없는 마지막 잠금이며, HTTP 라우터와 에이전트 루프 양쪽에서 같이 본다.

잠겨 있을 때도 막히는 것은 "주문 전송"과 "자동매매 가동"뿐이다. 자격증명 등록,
연결 테스트, 잔고·시세 조회는 그대로 되므로 실계좌 연결이 제대로 됐는지는
확인할 수 있다.
"""

from __future__ import annotations

from app.core.config import settings
from app.models import Env

LIVE_LOCK_MESSAGE = (
    "실계좌 주문이 서버에서 잠겨 있습니다. 모의투자에서 충분히 검증한 뒤 "
    "backend/.env 의 ALLOW_LIVE_TRADING=true 로 바꾸고 서버를 다시 띄우세요."
)


def live_trading_allowed() -> bool:
    return bool(settings.allow_live_trading)


def live_locked(env: Env) -> bool:
    """이 환경에서 주문이 잠겨 있는가. 모의투자는 항상 열려 있다."""
    return env == Env.live and not live_trading_allowed()


def lock_reason(env: Env) -> str | None:
    return LIVE_LOCK_MESSAGE if live_locked(env) else None
