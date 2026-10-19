"""논문 4.1~4.2절의 평가 절차.

- 시험 구간마다 계좌를 초기화하고 탐험 없이(greedy) 수행한다.
- 단일(평균): 시드별 단일 모델 결과의 산술평균. 앙상블: 같은 K개 모델의 결합.
- B&H: 첫 시험일 시가에 매수해 보유.
- 지표: 누적수익률, MDD, 연율화 샤프(무위험 0), 체결 후 평균 비중, 회전율.
- 표 3: k=1..K 의 모든 시드 조합. 다수결은 k=2에서 늘 1:1 동점이 되므로 k≥3만 본다.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from .backtester import run_backtest
from .ensemble import SeedEnsemble

REPORT_METRICS = ("cumulative_return", "mdd", "sharpe_ratio", "average_position", "turnover")


def _row(metrics: dict) -> dict:
    return {name: metrics.get(name) for name in REPORT_METRICS}


def evaluate_table2(ensemble: SeedEnsemble, test_df: pd.DataFrame) -> dict:
    """표 2: 단일 시드 각각 / 단일(평균) / 다수결 / Q평균 / B&H."""
    config = ensemble.config
    single = {}
    for seed, agent in zip(ensemble.seeds, ensemble.agents):
        single[seed] = run_backtest(test_df, config, agent=agent).metrics
    single_mean = {
        name: float(np.mean([m[name] for m in single.values() if m[name] is not None]))
        for name in REPORT_METRICS
    }
    mv = run_backtest(test_df, config, decide=ensemble.decider("mv"))
    qa = run_backtest(test_df, config, decide=ensemble.decider("qa"))
    bh = run_backtest(test_df, config, strategy="buy_and_hold")
    return {
        "single": {str(s): _row(m) for s, m in single.items()},
        "single_mean": single_mean,
        "mv": _row(mv.metrics),
        "qa": _row(qa.metrics),
        "buy_and_hold": _row(bh.metrics),
        "qa_unanimous_day_ratio": unanimous_ratio(ensemble, test_df, "qa"),
        "test_first_execution": str(qa.trades["date"].iloc[0].date()),
        "test_last_execution": str(qa.trades["date"].iloc[-1].date()),
        "test_steps": int(len(qa.trades)),
    }


def unanimous_ratio(ensemble: SeedEnsemble, test_df: pd.DataFrame, rule: str) -> float:
    """앙상블 운용 중 K개 모델이 모두 같은 행동을 고른 날의 비율 (논문 4.2절 마지막 문단)."""
    from .trading_env import TradingEnv

    env = TradingEnv.from_config(test_df, ensemble.config)
    state = env.reset()
    done, same, days = False, 0, 0
    while not done:
        decision = ensemble.decide(state, rule)
        same += int(len(set(decision.model_actions)) == 1)
        days += 1
        state, _, done, _ = env.step(decision.action)
    return same / days


def evaluate_table3(ensemble: SeedEnsemble, test_df: pd.DataFrame) -> list[dict]:
    """표 3: 결합 시드 수 k별 모든 조합의 시험 구간 수익률 (최저/평균/표준편차)."""
    config = ensemble.config
    rows = []
    for rule in ("mv", "qa"):
        for k in range(1, len(ensemble.seeds) + 1):
            if rule == "mv" and k == 2:
                continue
            returns = []
            for combo in combinations(ensemble.seeds, k):
                sub = ensemble.subset(combo)
                if k == 1:
                    result = run_backtest(test_df, config, agent=sub.agents[0])
                else:
                    result = run_backtest(test_df, config, decide=sub.decider(rule))
                returns.append(result.metrics["cumulative_return"])
            rows.append(
                {
                    "rule": rule,
                    "k": k,
                    "combinations": len(returns),
                    "min": float(np.min(returns)),
                    "mean": float(np.mean(returns)),
                    "std": float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0,
                }
            )
    return rows


def format_report(symbol: str, table2: dict, table3: list[dict]) -> str:
    pct = lambda v: "-" if v is None else f"{v * 100:.2f}"  # noqa: E731
    lines = [
        f"# 시드 앙상블 시험 결과 — {symbol}",
        "",
        f"시험 구간: {table2['test_first_execution']} ~ {table2['test_last_execution']} "
        f"({table2['test_steps']}거래일)",
        "",
        "| 전략 | 수익률(%) | MDD(%) | 샤프 | 평균 비중(%) | 회전율 |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    def add(label, m):
        sharpe = "-" if m["sharpe_ratio"] is None else f"{m['sharpe_ratio']:.2f}"
        lines.append(
            f"| {label} | {pct(m['cumulative_return'])} | {pct(m['mdd'])} | {sharpe} | "
            f"{pct(m['average_position'])} | {m['turnover']:.1f} |"
        )

    for seed, m in table2["single"].items():
        add(f"단일 seed-{seed}", m)
    add("단일(평균)", table2["single_mean"])
    add("다수결(MV)", table2["mv"])
    add("Q값 평균(QA)", table2["qa"])
    add("B&H", table2["buy_and_hold"])
    lines += [
        "",
        f"QA 운용 중 모든 모델이 같은 행동을 고른 날: {table2['qa_unanimous_day_ratio'] * 100:.1f}%",
        "",
        "## 결합 시드 수(k)별 수익률 (%)",
        "",
        "| 규칙 | k | 조합 수 | 최저 | 평균 | 표준편차 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in table3:
        lines.append(
            f"| {r['rule'].upper()} | {r['k']} | {r['combinations']} | {pct(r['min'])} | "
            f"{pct(r['mean'])} | {pct(r['std'])} |"
        )
    return "\n".join(lines) + "\n"
