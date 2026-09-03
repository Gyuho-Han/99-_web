from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, PlainSerializer


# ---------------------------------------------------------------------------
# 시각은 UTC임을 명시해서 내보낸다.
#
# DB 컬럼(SQLite DATETIME)은 타임존을 갖지 않고 값은 UTC로 들어간다. 그대로
# 직렬화하면 "2026-09-03T08:58:43" 처럼 나가고, 브라우저의 new Date() 는 이것을
# 로컬 시각으로 읽는다. 한국에서는 거래 시각이 9시간 전으로 보인다.
# 끝에 Z를 붙여 UTC임을 알려 주면 화면이 알아서 로컬로 환산한다.
# ---------------------------------------------------------------------------
def _as_utc_iso(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc_iso, return_type=str)]


# -- 인증 -------------------------------------------------------------------
class SignupIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: str
    name: str

    class Config:
        from_attributes = True


# -- 자격증명 ---------------------------------------------------------------
class CredentialIn(BaseModel):
    broker: Literal["kis"] = "kis"
    env: Literal["paper", "live"]
    market: Literal["kr", "us"] = "kr"
    label: str = ""
    app_key: str = Field(min_length=8)
    app_secret: str = Field(min_length=8)
    account_no: str = Field(min_length=8, description="국내는 종합계좌, 미국은 해외주식 계좌. 예: 50123456-01")


class CredentialOut(BaseModel):
    id: int
    broker: str
    env: str
    market: str
    label: str
    app_key_masked: str
    account_no_masked: str
    is_active: bool
    last_verified_at: UtcTime | None
    last_error: str | None
    updated_at: UtcTime


class VerifyOut(BaseModel):
    ok: bool
    message: str


# -- 시세 -------------------------------------------------------------------
class QuoteOut(BaseModel):
    symbol: str
    name: str
    currency: str = "KRW"
    exchange: str = ""
    price: float
    prev_close: float
    change: float
    change_pct: float
    open: float
    high: float
    low: float
    volume: int
    # 현재가 조회 시각. DB에 저장되는 값이 아니라 어댑터가 응답을 만들 때 찍는
    # 로컬 시각이라, 저장 시각(UTC)과 달리 그대로 내보낸다.
    ts: datetime


class CandleOut(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


# -- 계좌 -------------------------------------------------------------------
class HoldingOut(BaseModel):
    symbol: str
    name: str
    quantity: int
    avg_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pct: float
    weight_pct: float


class AccountOut(BaseModel):
    env: str
    market: str
    currency: str
    connected: bool
    broker: str
    cash: float
    holdings_value: float
    total_equity: float
    deposit_total: float
    total_pnl: float
    total_pnl_pct: float
    day_pnl: float
    day_pnl_pct: float
    holdings: list[HoldingOut]


class PositionStat(BaseModel):
    """거래했던 종목의 누적 기록. 지금 보유 중이 아니어도 남는다."""

    symbol: str
    name: str
    realized_pnl: float
    trade_count: int
    last_traded_at: UtcTime | None = None


class PortfolioHolding(HoldingOut):
    realized_pnl: float = 0.0
    trade_count: int = 0
    last_traded_at: UtcTime | None = None


class PortfolioOut(AccountOut):
    holdings: list[PortfolioHolding]
    # 지금은 갖고 있지 않지만 거래한 적 있는 종목
    closed: list[PositionStat]
    cash_weight_pct: float
    realized_total: float
    # 실현손익을 신뢰할 수 있는 상태인지. 실계좌 체결은 취득단가를 증권사가 갖고 있어
    # 우리가 채우지 않으므로 False가 된다. 화면이 0원을 사실처럼 보여 주면 안 된다.
    realized_supported: bool


# -- 주문 -------------------------------------------------------------------
class OrderIn(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: float = 0
    order_type: Literal["limit", "market"] = "limit"


class OrderOut(BaseModel):
    id: int
    broker_order_id: str | None
    symbol: str
    name: str
    side: str
    order_type: str
    quantity: int
    price: float
    filled_quantity: int
    filled_price: float
    fee: float
    realized_pnl: float
    status: str
    source: str
    note: str | None
    created_at: UtcTime
    filled_at: UtcTime | None

    class Config:
        from_attributes = True


class OrderPage(BaseModel):
    items: list[OrderOut]
    total: int
    page: int
    page_size: int


# -- 성과 -------------------------------------------------------------------
class EquityPoint(BaseModel):
    date: str
    equity: float
    benchmark: float
    drawdown: float


class PerformanceOut(BaseModel):
    env: str
    market: str
    currency: str
    metrics: dict
    benchmark_metrics: dict
    curve: list[EquityPoint]
    monthly: list[dict]


# -- 에이전트 ---------------------------------------------------------------
class AgentConfigIn(BaseModel):
    enabled: bool | None = None
    # 자동매매를 켤 때 한 번만 필요한 플래그. 리스크 한도를 확인했다는 뜻이며
    # 설정으로 저장되지 않는다 (AgentConfig.risk_ack_at 시각만 남는다).
    risk_ack: bool = False
    model_name: str | None = None
    universe: str | None = None
    max_position_pct: float | None = Field(default=None, ge=1, le=100)
    max_order_amount: float | None = Field(default=None, ge=10_000)
    daily_loss_limit_pct: float | None = Field(default=None, ge=0.5, le=50)
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    order_cooldown_seconds: int | None = Field(default=None, ge=0, le=86_400)
    max_daily_orders: int | None = Field(default=None, ge=1, le=1_000)
    trading_start: str | None = None
    trading_end: str | None = None


class AgentConfigOut(BaseModel):
    env: str
    market: str
    enabled: bool
    risk_ack_at: UtcTime | None = None
    live_locked: bool = False
    account_linked: bool = False
    model_name: str
    available_models: list[str]
    universe: list[str]
    max_position_pct: float
    max_order_amount: float
    daily_loss_limit_pct: float
    confidence_threshold: float
    order_cooldown_seconds: int
    max_daily_orders: int
    trading_start: str
    trading_end: str
    updated_at: UtcTime


class SignalOut(BaseModel):
    id: int
    symbol: str
    action: str
    confidence: float
    q_buy: float
    q_hold: float
    q_sell: float
    price: float
    executed: bool
    reason: str | None
    created_at: UtcTime

    class Config:
        from_attributes = True


TokenOut.model_rebuild()
