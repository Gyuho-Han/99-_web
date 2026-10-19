"""Performance definitions used identically for agent, cash and buy-and-hold."""

from collections import deque
import numpy as np
import pandas as pd


def drawdown(equity: pd.Series) -> pd.Series:
    """Negative drawdown series; metrics report MDD as a positive loss magnitude."""
    return equity / equity.cummax() - 1.0


def holding_statistics(trades: pd.DataFrame) -> dict:
    """FIFO share-weighted holding sessions for sold shares; open lots reported apart."""
    lots = deque()
    sold_shares = 0
    weighted_days = 0.0
    for step, row in enumerate(trades.itertuples(index=False), start=1):
        quantity = int(row.shares_traded)
        if row.trade_type == "buy" and quantity:
            lots.append([step, quantity])
        elif row.trade_type == "sell":
            remaining = quantity
            while remaining:
                if not lots:
                    raise ValueError("Sell history exceeds recorded buys.")
                bought_at, available = lots[0]
                matched = min(available, remaining)
                weighted_days += matched * (step - bought_at)
                sold_shares += matched
                remaining -= matched
                lots[0][1] -= matched
                if lots[0][1] == 0:
                    lots.popleft()
    return {
        "average_holding_days": weighted_days / sold_shares if sold_shares else None,
        "closed_shares": sold_shares,
        "open_shares": sum(lot[1] for lot in lots),
    }


def calculate_metrics(
    equity, trades=None, *, periods_per_year=252, annual_risk_free_rate=0.0
):
    """Use close-to-close simple returns; include the initial pre-trade account value.

    Sharpe: sample standard deviation of excess daily returns.
    Sortino: sqrt(mean(min(excess_return, 0)^2)) over ALL days.
    Undefined ratios and holding durations are None, serialized as JSON null.
    """
    values = pd.Series(equity, dtype=float)
    if len(values) < 2 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Need at least two finite, strictly positive equity values.")
    if (
        periods_per_year <= 0
        or not np.isfinite(annual_risk_free_rate)
        or annual_risk_free_rate <= -1
    ):
        raise ValueError("Invalid annualization settings.")
    returns = values.pct_change().dropna()
    risk_free_daily = (1 + annual_risk_free_rate) ** (1 / periods_per_year) - 1
    excess = returns.to_numpy() - risk_free_daily
    deviation = float(np.std(excess, ddof=1)) if len(excess) > 1 else 0.0
    downside = float(np.sqrt(np.mean(np.minimum(excess, 0.0) ** 2)))

    def ratio(denominator):
        return (
            float(np.sqrt(periods_per_year) * np.mean(excess) / denominator)
            if denominator > 1e-12
            else None
        )

    trade_frame = (
        trades
        if trades is not None
        else pd.DataFrame(columns=["trade_type", "shares_traded", "turnover"])
    )
    return {
        "cumulative_return": float(values.iloc[-1] / values.iloc[0] - 1),
        "mdd": max(0.0, float(-drawdown(values).min())),
        "sharpe_ratio": ratio(deviation),
        "sortino_ratio": ratio(downside),
        "trade_count": int((trade_frame["shares_traded"] > 0).sum()),
        "turnover": float(trade_frame["turnover"].sum()),
        # 논문 표 2 "평균 비중": 매 거래일 체결 직후 주식 비중의 평균.
        "average_position": (
            float(trade_frame["executed_target"].mean())
            if "executed_target" in trade_frame and len(trade_frame)
            else None
        ),
        "initial_asset": float(values.iloc[0]),
        "final_asset": float(values.iloc[-1]),
        "steps": len(returns),
        **holding_statistics(trade_frame),
    }
