from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


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
    last_verified_at: datetime | None
    last_error: str | None
    updated_at: datetime


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
    created_at: datetime
    filled_at: datetime | None

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
    model_name: str | None = None
    universe: str | None = None
    max_position_pct: float | None = Field(default=None, ge=1, le=100)
    max_order_amount: float | None = Field(default=None, ge=10_000)
    daily_loss_limit_pct: float | None = Field(default=None, ge=0.5, le=50)
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    trading_start: str | None = None
    trading_end: str | None = None


class AgentConfigOut(BaseModel):
    env: str
    market: str
    enabled: bool
    model_name: str
    available_models: list[str]
    universe: list[str]
    max_position_pct: float
    max_order_amount: float
    daily_loss_limit_pct: float
    confidence_threshold: float
    trading_start: str
    trading_end: str
    updated_at: datetime


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
    created_at: datetime

    class Config:
        from_attributes = True


TokenOut.model_rebuild()
