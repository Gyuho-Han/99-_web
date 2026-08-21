"""위험조정 성과 지표.

절대수익보다 위험조정수익(Sharpe, MDD)을 성과 기준으로 삼는다는
프로젝트 설계 원칙을 그대로 반영한다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

TRADING_DAYS = 252
RISK_FREE_ANNUAL = 0.032  # 국고채 3년 근사치. 필요 시 설정으로 뺀다.


@dataclass
class Metrics:
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    calmar: float
    volatility_pct: float
    win_rate_pct: float
    profit_factor: float
    trades: int
    best_day_pct: float
    worst_day_pct: float

    def dict(self) -> dict:
        return asdict(self)


def daily_returns(equity: list[float]) -> list[float]:
    return [
        equity[i] / equity[i - 1] - 1
        for i in range(1, len(equity))
        if equity[i - 1]
    ]


def max_drawdown(equity: list[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd * 100


def drawdown_series(equity: list[float]) -> list[float]:
    peak, out = -math.inf, []
    for v in equity:
        peak = max(peak, v)
        out.append((v / peak - 1) * 100 if peak > 0 else 0.0)
    return out


def compute(equity: list[float], trade_pnls: list[float] | None = None) -> Metrics:
    trade_pnls = trade_pnls or []
    if len(equity) < 2:
        return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0, len(trade_pnls), 0, 0)

    rets = daily_returns(equity)
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    std = math.sqrt(var)

    total_return = (equity[-1] / equity[0] - 1) * 100
    years = max(n / TRADING_DAYS, 1 / TRADING_DAYS)
    cagr = ((equity[-1] / equity[0]) ** (1 / years) - 1) * 100 if equity[0] > 0 else 0.0

    rf_daily = RISK_FREE_ANNUAL / TRADING_DAYS
    sharpe = ((mean - rf_daily) / std * math.sqrt(TRADING_DAYS)) if std else 0.0

    downside = [r for r in rets if r < rf_daily]
    dstd = math.sqrt(sum((r - rf_daily) ** 2 for r in downside) / len(downside)) if downside else 0.0
    sortino = ((mean - rf_daily) / dstd * math.sqrt(TRADING_DAYS)) if dstd else 0.0

    mdd = max_drawdown(equity)
    calmar = (cagr / abs(mdd)) if mdd else 0.0

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate = (len(wins) / len(trade_pnls) * 100) if trade_pnls else 0.0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss else (gross_win and 99.0 or 0.0)

    return Metrics(
        total_return_pct=round(total_return, 2),
        cagr_pct=round(cagr, 2),
        sharpe=round(sharpe, 2),
        sortino=round(sortino, 2),
        max_drawdown_pct=round(mdd, 2),
        calmar=round(calmar, 2),
        volatility_pct=round(std * math.sqrt(TRADING_DAYS) * 100, 2),
        win_rate_pct=round(win_rate, 1),
        profit_factor=round(profit_factor, 2),
        trades=len(trade_pnls),
        best_day_pct=round(max(rets) * 100, 2),
        worst_day_pct=round(min(rets) * 100, 2),
    )


def monthly_returns(dates: list[str], equity: list[float]) -> list[dict]:
    """YYYY-MM 단위 수익률. 히트맵/막대에 쓴다."""
    buckets: dict[str, list[float]] = {}
    for d, v in zip(dates, equity):
        buckets.setdefault(d[:7], []).append(v)
    out = []
    prev_close = None
    for month in sorted(buckets):
        vals = buckets[month]
        start = prev_close if prev_close is not None else vals[0]
        out.append({"month": month, "return_pct": round((vals[-1] / start - 1) * 100, 2)})
        prev_close = vals[-1]
    return out
