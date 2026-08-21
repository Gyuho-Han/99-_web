"""ORM 모델.

계좌 환경(env)은 'paper'(모의투자) / 'live'(실계좌) 두 가지이며,
포지션·주문·에이전트 설정·일별 스냅샷 모두 env로 분리 저장된다.
따라서 화면 상단 토글 하나로 두 환경을 완전히 독립적으로 볼 수 있다.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Env(str, enum.Enum):
    paper = "paper"
    live = "live"


class Side(str, enum.Enum):
    buy = "buy"
    sell = "sell"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    filled = "filled"
    partial = "partial"
    canceled = "canceled"
    rejected = "rejected"


class AgentAction(str, enum.Enum):
    buy = "buy"
    hold = "hold"
    sell = "sell"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    credentials: Mapped[list["BrokerCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class BrokerCredential(Base):
    """증권사 API 자격증명. app_secret과 계좌번호는 암호화 저장한다."""

    __tablename__ = "broker_credentials"
    __table_args__ = (UniqueConstraint("user_id", "broker", "env", name="uq_cred"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    broker: Mapped[str] = mapped_column(String(32), default="kis")
    env: Mapped[Env] = mapped_column(Enum(Env), default=Env.paper)
    label: Mapped[str] = mapped_column(String(80), default="")

    app_key_enc: Mapped[str] = mapped_column(Text)
    app_secret_enc: Mapped[str] = mapped_column(Text)
    account_no_enc: Mapped[str] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="credentials")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("user_id", "env", "symbol", name="uq_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    env: Mapped[Env] = mapped_column(Enum(Env), default=Env.paper, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    env: Mapped[Env] = mapped_column(Enum(Env), default=Env.paper, index=True)

    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    side: Mapped[Side] = mapped_column(Enum(Side))
    order_type: Mapped[str] = mapped_column(String(16), default="limit")  # limit | market
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    filled_price: Mapped[float] = mapped_column(Float, default=0.0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    tax: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.pending)
    source: Mapped[str] = mapped_column(String(16), default="agent")  # agent | manual
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentConfig(Base):
    """자동매매 실행 설정 및 리스크 한도."""

    __tablename__ = "agent_configs"
    __table_args__ = (UniqueConstraint("user_id", "env", name="uq_agent_cfg"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    env: Mapped[Env] = mapped_column(Enum(Env), default=Env.paper, index=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    model_name: Mapped[str] = mapped_column(String(64), default="ppo-ensemble-v0")
    universe: Mapped[str] = mapped_column(Text, default="005930")  # 콤마 구분 종목코드

    max_position_pct: Mapped[float] = mapped_column(Float, default=30.0)   # 종목당 최대 비중(%)
    max_order_amount: Mapped[float] = mapped_column(Float, default=2_000_000)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, default=3.0)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.55)
    trading_start: Mapped[str] = mapped_column(String(5), default="09:05")
    trading_end: Mapped[str] = mapped_column(String(5), default="15:15")

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AgentSignal(Base):
    """RL 정책의 매 스텝 출력. 실제 모델을 붙이면 이 테이블만 채우면 된다."""

    __tablename__ = "agent_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    env: Mapped[Env] = mapped_column(Enum(Env), default=Env.paper, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[AgentAction] = mapped_column(Enum(AgentAction))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    q_buy: Mapped[float] = mapped_column(Float, default=0.0)
    q_hold: Mapped[float] = mapped_column(Float, default=0.0)
    q_sell: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class EquitySnapshot(Base):
    """일별 자산 스냅샷. 수익곡선·MDD·Sharpe 계산의 원천."""

    __tablename__ = "equity_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "env", "date", name="uq_equity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    env: Mapped[Env] = mapped_column(Enum(Env), default=Env.paper, index=True)
    date: Mapped[date] = mapped_column(Date, index=True)

    cash: Mapped[float] = mapped_column(Float, default=0.0)
    holdings_value: Mapped[float] = mapped_column(Float, default=0.0)
    total_equity: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_value: Mapped[float] = mapped_column(Float, default=0.0)  # KOSPI 기준 Buy&Hold


class AuditLog(Base):
    """자격증명 변경·자동매매 토글 등 민감 행위 기록."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class CashAccount(Base):
    __tablename__ = "cash_accounts"
    __table_args__ = (UniqueConstraint("user_id", "env", name="uq_cash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    env: Mapped[Env] = mapped_column(Enum(Env), default=Env.paper, index=True)
    cash: Mapped[float] = mapped_column(Float, default=10_000_000)
    deposit_total: Mapped[float] = mapped_column(Float, default=10_000_000)
