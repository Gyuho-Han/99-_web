"""Local simulated account shared by training, backtests and historical paper runs."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TradeExecution:
    trade_type: str
    shares_traded: int
    trade_value: float
    fee: float
    tax: float
    turnover: float
    requested_target: float
    executed_target: float
    min_holding_blocked: bool


class PaperBroker:
    """Long-only, whole-share account. The caller supplies prices and trading days."""

    def __init__(
        self,
        initial_balance=10_000_000,
        commission=0.00015,
        tax=0.0025,
        min_holding_days=0,
    ):
        if not math.isfinite(initial_balance) or initial_balance <= 0:
            raise ValueError("initial_balance must be positive and finite.")
        if any(
            not math.isfinite(rate) or not 0 <= rate < 1 for rate in (commission, tax)
        ):
            raise ValueError("Costs must be finite rates in [0, 1).")
        if commission + tax >= 1:
            raise ValueError("Selling costs must be below 100%.")
        if type(min_holding_days) is not int or min_holding_days < 0:
            raise ValueError("min_holding_days must be a nonnegative integer.")
        self.initial_balance = float(initial_balance)
        self.commission = float(commission)
        self.tax = float(tax)
        self.min_holding_days = min_holding_days
        self.reset()

    def reset(self):
        self.cash = self.initial_balance
        self.shares = 0
        self.holding_days = 0
        self.trade_count = 0
        self.total_turnover = 0.0

    def portfolio_value(self, price):
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive and finite.")
        return float(self.cash + self.shares * price)

    def hold(self, price):
        ratio = self.shares * price / self.portfolio_value(price)
        return TradeExecution("hold", 0, 0.0, 0.0, 0.0, 0.0, ratio, ratio, False)

    def rebalance(self, target_ratio, price):
        """Use pre-cost target equity and optionally lock reductions after buys."""
        if not math.isfinite(target_ratio) or not 0 <= target_ratio <= 1:
            raise ValueError("target_ratio must be within [0, 1].")
        asset = self.portfolio_value(price)
        target_shares = int((target_ratio * asset) // price)
        change = target_shares - self.shares
        blocked = change < 0 and self.holding_days < self.min_holding_days
        if blocked:
            change = 0
        if change > 0:
            affordable = int(self.cash // (price * (1 + self.commission)))
            change = min(change, affordable)
        value = abs(change) * price
        fee = value * self.commission
        tax = value * self.tax if change < 0 else 0.0
        self.cash -= change * price + fee + tax
        self.shares += change
        if change > 0 or self.shares == 0:
            self.holding_days = 0
        turnover = value / asset
        self.total_turnover += turnover
        self.trade_count += int(change != 0)
        direction = "buy" if change > 0 else "sell" if change < 0 else "hold"
        return TradeExecution(
            direction,
            abs(change),
            value,
            fee,
            tax,
            turnover,
            target_ratio,
            self.shares * price / self.portfolio_value(price),
            blocked,
        )

    def finish_day(self):
        """Call once at each trading close, including the day of a new buy."""
        self.holding_days = self.holding_days + 1 if self.shares > 0 else 0

    def snapshot(self, price):
        return {
            "cash": self.cash,
            "shares": self.shares,
            "asset_value": self.portfolio_value(price),
            "holding_days": self.holding_days,
            "trade_count": self.trade_count,
            "turnover": self.total_turnover,
        }
