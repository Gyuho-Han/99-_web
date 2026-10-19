"""Daily, single-stock simulator. This file never sends real orders.

Timing: observe through close[t] -> execute at open[t+1] -> value at close[t+1].
Reward includes overnight changes in existing holdings and new trading costs.
Source: su08035-ops/auto_trading backend/env/trading_env.py (unchanged logic).
"""

from __future__ import annotations

from dataclasses import asdict
from numbers import Integral
from typing import Any

import numpy as np
import pandas as pd

from .features import get_market_feature_names
from .paper_broker import PaperBroker, TradeExecution


DEFAULT_PORTFOLIO_FEATURES = ["position_ratio"]


class TradingEnv:
    """Own the market clock, account, execution, state and reward, not learning."""

    def __init__(
        self,
        feature_df: pd.DataFrame,
        *,
        market_features: list[str],
        window: int = 20,
        action_values: list[float] | tuple[float, ...] = (0.0, 0.5, 1.0),
        portfolio_features: list[str] | None = None,
        initial_balance: float = 10_000_000,
        commission: float = 0.00015,
        tax: float = 0.0025,
        min_holding_days: int = 0,
    ) -> None:
        self.df = feature_df.sort_index().copy()
        self.market_features = list(market_features)
        self.portfolio_features = list(
            DEFAULT_PORTFOLIO_FEATURES
            if portfolio_features is None
            else portfolio_features
        )
        self.window = window
        self.action_values = list(action_values)
        self.initial_balance = float(initial_balance)
        self.commission = float(commission)
        self.tax = float(tax)
        self.min_holding_days = min_holding_days
        self._validate_inputs()
        self.broker = PaperBroker(
            self.initial_balance, self.commission, self.tax, self.min_holding_days
        )

        self.feature_values = self.df[self.market_features].to_numpy(
            dtype=np.float32, copy=True
        )
        if not np.isfinite(self.feature_values).all():
            raise ValueError(
                "Market features must remain finite when converted to float32."
            )
        self.open_prices = self.df["open"].to_numpy(dtype=float, copy=True)
        self.prices = self.df["close"].to_numpy(dtype=float, copy=True)
        self.dates = self.df.index
        self.reset()

    @classmethod
    def from_config(
        cls, feature_df: pd.DataFrame, config: dict[str, Any]
    ) -> "TradingEnv":
        """Read the state/action/reward/environment sections of the configuration."""
        if config["action"]["type"] != "target_position":
            raise ValueError("This environment supports target_position actions only.")
        if config["reward"]["type"] != "log_return":
            raise ValueError("This environment supports log_return rewards only.")
        settings = config["environment"]
        return cls(
            feature_df,
            market_features=get_market_feature_names(config),
            window=config["state"]["window"],
            action_values=config["action"]["values"],
            portfolio_features=config["state"].get("portfolio_features"),
            initial_balance=settings["initial_balance"],
            commission=settings["commission"],
            tax=settings["tax"],
            min_holding_days=settings["min_holding_days"],
        )

    @property
    def state_dim(self) -> int:
        return self.window * len(self.market_features) + len(self.portfolio_features)

    @property
    def action_size(self) -> int:
        return len(self.action_values)

    @property
    def episode_steps(self) -> int:
        """Available transitions after the initial observation window."""
        return len(self.df) - self.window

    def reset(self) -> np.ndarray:
        """Reset only the simulated account and clock, not the external agent."""
        self.current_step = self.window - 1
        self.broker.reset()
        self.asset_value = self.initial_balance
        self.portfolio_values: list[float] = [self.asset_value]
        self.action_history: list[int] = []
        self.trade_history: list[dict[str, Any]] = []
        return self._get_observation()

    def step(
        self, action: int, *, rebalance: bool = True
    ) -> tuple[np.ndarray, float, bool, dict[str, Any]]:
        """Advance one trading day and return (next_state, reward, done, info)."""
        if self.current_step >= len(self.df) - 1:
            raise RuntimeError("Episode is already done. Call reset() first.")
        if isinstance(action, (bool, np.bool_)) or not isinstance(action, Integral):
            raise ValueError("action must be an integer index, not a target ratio.")
        if not 0 <= action < self.action_size:
            raise ValueError(f"Invalid action index: {action}")
        action = int(action)

        # 1. The decision sees only information available at the current close.
        previous_asset = self._portfolio_value(self.prices[self.current_step])
        decision_date = self.dates[self.current_step]
        next_step = self.current_step + 1

        # 2. Execute at the next open. Existing shares also earn the overnight gap.
        execution_price = float(self.open_prices[next_step])
        opening_asset = self._portfolio_value(execution_price)
        if rebalance:
            execution = self._rebalance_to_target(
                target_ratio=self.action_values[action],
                price=execution_price,
                current_asset=opening_asset,
            )
        else:
            execution = self.broker.hold(execution_price)

        # 3. Mark the account at the next close, then calculate net log return.
        self.current_step = next_step
        self.asset_value = self._portfolio_value(self.prices[self.current_step])
        reward = float(np.log(self.asset_value / previous_asset))
        self.broker.finish_day()
        done = self.current_step == len(self.df) - 1

        self.action_history.append(action)
        self.portfolio_values.append(self.asset_value)
        self.trade_history.append(
            {
                "date": self.dates[self.current_step],
                "decision_date": decision_date,
                "execution_price": execution_price,
                "action": action,
                **asdict(execution),
            }
        )
        info = {
            "date": self.dates[self.current_step],
            "decision_date": decision_date,
            "execution_price": execution_price,
            "price": float(self.prices[self.current_step]),
            "cash": self.cash,
            "shares": self.shares,
            "asset_value": self.asset_value,
            "reward": reward,
            "trade_count": self.trade_count,
            "total_turnover": self.total_turnover,
            "holding_days": self.holding_days,
            "execution": execution,
        }
        return self._get_observation(), reward, done, info

    def _get_observation(self) -> np.ndarray:
        """Flatten the trailing market window, then append portfolio features."""
        end = self.current_step + 1
        market_state = self.feature_values[end - self.window : end].reshape(-1)
        position_ratio = self._position_ratio(
            asset=self.asset_value, price=self.prices[self.current_step]
        )
        portfolio_values = {"position_ratio": position_ratio}
        portfolio_state = np.array(
            [portfolio_values[name] for name in self.portfolio_features],
            dtype=np.float32,
        )
        return np.concatenate([market_state, portfolio_state]).astype(np.float32)

    @property
    def cash(self):
        return self.broker.cash

    @property
    def shares(self):
        return self.broker.shares

    @property
    def holding_days(self):
        return self.broker.holding_days

    @property
    def trade_count(self):
        return self.broker.trade_count

    @property
    def total_turnover(self):
        return self.broker.total_turnover

    def _rebalance_to_target(
        self, *, target_ratio: float, price: float, current_asset: float
    ) -> TradeExecution:
        return self.broker.rebalance(target_ratio, price)

    def _portfolio_value(self, price: float) -> float:
        return self.broker.portfolio_value(price)

    def _position_ratio(self, *, asset: float, price: float) -> float:
        return float(self.shares * price / asset)

    def _validate_inputs(self) -> None:
        """Reject invalid data before it produces NaN states or undefined rewards."""
        if type(self.window) is not int or self.window <= 0:
            raise ValueError("window must be a positive integer.")
        if len(self.df) < self.window + 1:
            raise ValueError("Need at least window + 1 rows for one transition.")
        if not isinstance(self.df.index, pd.DatetimeIndex):
            raise ValueError("feature_df must have a DatetimeIndex.")
        if (
            self.df.index.hasnans
            or not self.df.index.is_unique
            or not self.df.columns.is_unique
        ):
            raise ValueError("Dates and column names must be valid and unique.")
        if not self.market_features or len(set(self.market_features)) != len(
            self.market_features
        ):
            raise ValueError("market_features must be nonempty and unique.")
        required_columns = ["open", "close", *self.market_features]
        missing = [name for name in required_columns if name not in self.df.columns]
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        if not np.isfinite(self.df[required_columns].to_numpy(dtype=float)).all():
            raise ValueError(
                "Prices and features must be finite; remove warm-up NaNs first."
            )
        if (self.df[["open", "close"]].to_numpy(dtype=float) <= 0).any():
            raise ValueError("Prices must be strictly positive.")
        if len(set(self.portfolio_features)) != len(self.portfolio_features):
            raise ValueError("portfolio_features must be unique.")
        if any(
            name not in DEFAULT_PORTFOLIO_FEATURES for name in self.portfolio_features
        ):
            raise ValueError("Only position_ratio is supported as a portfolio feature.")
        if not self.action_values or any(
            not np.isfinite(value) or not 0 <= value <= 1
            for value in self.action_values
        ):
            raise ValueError("Action target ratios must be finite and within [0, 1].")
        if len(set(self.action_values)) != len(self.action_values):
            raise ValueError("Action target ratios must be unique.")
        if not np.isfinite(self.initial_balance) or self.initial_balance <= 0:
            raise ValueError("initial_balance must be finite and positive.")
        if any(
            not np.isfinite(rate) or not 0 <= rate < 1
            for rate in (self.commission, self.tax)
        ):
            raise ValueError("commission and tax must be finite rates in [0, 1).")
        if self.commission + self.tax >= 1:
            raise ValueError("Combined selling costs must be below 100%.")
        if type(self.min_holding_days) is not int or self.min_holding_days < 0:
            raise ValueError("min_holding_days must be a nonnegative integer.")
