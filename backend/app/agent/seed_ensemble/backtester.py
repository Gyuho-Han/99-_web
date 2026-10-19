"""Independent chronological evaluation. This module never trains an agent."""

from dataclasses import dataclass
import pandas as pd

from .metrics import calculate_metrics
from .trading_env import TradingEnv


@dataclass
class BacktestResult:
    name: str
    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict


def run_backtest(
    feature_df, config, *, agent=None, strategy="agent", decide=None
) -> BacktestResult:
    """Run one frozen policy on its own simulated account.

    decide(state) -> action index lets a seed ensemble (ensemble.py) trade on the
    SAME environment as a single agent. The ensemble's state therefore contains
    the ensemble's own position_ratio, as the paper requires (3.2).
    """
    if strategy not in {"agent", "cash", "buy_and_hold"}:
        raise ValueError(f"Unsupported strategy: {strategy}")
    if strategy == "agent" and (agent is None) == (decide is None):
        raise ValueError("Agent strategy requires exactly one of agent or decide.")
    env = TradingEnv.from_config(feature_df, config)
    if strategy == "cash" and 0.0 not in env.action_values:
        raise ValueError("Cash benchmark needs a 0% action.")
    if strategy == "buy_and_hold" and 1.0 not in env.action_values:
        raise ValueError("Buy-and-hold benchmark needs a 100% action.")
    state = env.reset()
    done = False
    step = 0
    was_training = agent.policy_network.training if agent is not None else False
    if agent is not None:
        agent.policy_network.eval()
    try:
        while not done:
            if strategy == "agent" and decide is not None:
                action = int(decide(state))
            elif strategy == "agent":
                action = agent.select_action(state, explore=False)
            elif strategy == "cash":
                action = env.action_values.index(0.0)
            else:
                action = env.action_values.index(1.0)
            # Buy once and retain the same shares; never rebalance the benchmark daily.
            state, _, done, _ = env.step(
                action, rebalance=not (strategy == "buy_and_hold" and step > 0)
            )
            step += 1
    finally:
        if agent is not None:
            agent.policy_network.train(was_training)
    equity = pd.Series(
        env.portfolio_values,
        index=env.dates[env.window - 1 :],
        name=strategy,
        dtype=float,
    )
    trades = pd.DataFrame(env.trade_history)
    settings = config["evaluation"]
    metrics = calculate_metrics(
        equity,
        trades,
        periods_per_year=settings["periods_per_year"],
        annual_risk_free_rate=settings["annual_risk_free_rate"],
    )
    return BacktestResult(strategy, equity, trades, metrics)
