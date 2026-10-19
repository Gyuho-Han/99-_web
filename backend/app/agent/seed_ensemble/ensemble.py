"""시드 앙상블: 서로 다른 난수 시드로 학습한 DQN K개의 판단을 하나로 모은다.

논문 「시드 앙상블을 통한 DQN 주식 비중 조절의 성과 및 안정성 개선」 3.2절.

    단일 모델   π_k(s)  = argmax_a Q_k(s, a)
    다수결(MV)  π_MV(s) = argmin_{a ∈ A*} w_a,   A* = argmax_a |{k : π_k(s) = a}|     (식 2)
    Q값 평균(QA) π_QA(s) = argmax_a (1/K) Σ_k Q_k(s, a)                               (식 3)

- 동점이면 MV는 목표 비중 w_a가 가장 작은 행동을 택한다(의견이 갈릴 때 보수적으로).
- QA의 평균 Q값이 정확히 같은 경우는 논문에 규칙이 없다. 실수 값이라 사실상 생기지
  않지만, 생기면 MV와 같은 방향(작은 비중)으로 정해 결과가 실행 순서에 좌우되지 않게 했다.
- 상태의 보유 비중(position_ratio)에는 앙상블 자신의 계좌 값을 쓴다. 그래서 백테스트도
  개별 모델 계좌를 섞지 않고, 앙상블이 낸 행동으로 움직이는 계좌 하나를 따로 돌린다.
- 결합 규칙은 학습이 끝난 모델만 쓴다. 추가 학습은 없다.

학습 자체(DQN, 환경, 피처, 검증 기반 에피소드 선택)는 su08035-ops/auto_trading 의
backend 코드를 그대로 옮긴 같은 패키지의 모듈들이 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import torch

from .dqn import DQNAgent
from .features import get_market_feature_names, make_features
from .train import load_checkpoint

RULES = ("mv", "qa", "single")
RULE_LABEL = {"mv": "다수결(MV)", "qa": "Q값 평균(QA)", "single": "단일 시드"}
CHECKPOINT_NAME = "dqn_model.pth"


@dataclass(frozen=True)
class EnsembleDecision:
    action: int                     # 행동 인덱스
    target_weight: float            # 목표 주식 비중 w_a
    rule: str                       # mv | qa | single
    q_values: np.ndarray            # (K, A) 모델별 Q값
    model_actions: tuple[int, ...]  # 모델별 argmax 행동
    votes: tuple[int, ...]          # 행동별 득표 수 (길이 A)

    @property
    def mean_q(self) -> np.ndarray:
        return self.q_values.mean(axis=0)

    @property
    def agreement(self) -> float:
        """선택된 행동과 같은 행동을 고른 모델의 비율 (0~1)."""
        return self.votes[self.action] / len(self.model_actions)


class SeedEnsemble:
    """같은 설정 · 다른 시드로 학습한 DQN K개."""

    def __init__(self, agents: Sequence[DQNAgent], seeds: Sequence[int], config: dict):
        if not agents or len(agents) != len(seeds):
            raise ValueError("Need one seed label per agent.")
        dims = {(a.state_dim, a.action_dim) for a in agents}
        if len(dims) != 1:
            raise ValueError(f"All seed models must share state/action dims: {dims}")
        self.agents = list(agents)
        self.seeds = [int(s) for s in seeds]
        self.config = config
        self.state_dim, self.action_dim = dims.pop()
        self.action_values = [float(v) for v in config["action"]["values"]]
        if len(self.action_values) != self.action_dim:
            raise ValueError("Checkpoint action values do not match network outputs.")
        self.window = int(config["state"]["window"])
        self.market_features = get_market_feature_names(config)
        for agent in self.agents:
            agent.policy_network.eval()

    # -- 불러오기 -------------------------------------------------------------
    @classmethod
    def load(cls, model_dir: str | Path, seeds: Iterable[int] | None = None) -> "SeedEnsemble":
        """model_dir/seed-<k>/dqn_model.pth 들을 시드 순서대로 불러온다."""
        model_dir = Path(model_dir)
        found = {}
        for path in sorted(model_dir.glob(f"seed-*/{CHECKPOINT_NAME}")):
            try:
                found[int(path.parent.name.split("-", 1)[1])] = path
            except ValueError:
                continue
        wanted = sorted(found) if seeds is None else [int(s) for s in seeds]
        missing = [s for s in wanted if s not in found]
        if missing or not wanted:
            raise FileNotFoundError(
                f"{model_dir}: seed checkpoints missing {missing or 'all'}"
            )
        agents, configs = [], []
        for seed in wanted:
            agent, config, _ = load_checkpoint(found[seed])
            agents.append(agent)
            configs.append(config)
        base = configs[0]
        for seed, config in zip(wanted, configs):
            for section in ("state", "action", "reward", "environment"):
                if config[section] != base[section]:
                    raise ValueError(
                        f"seed-{seed} was trained with a different '{section}' setting."
                    )
            if config["agent"] != base["agent"]:
                raise ValueError(f"seed-{seed} has different DQN hyperparameters.")
        return cls(agents, wanted, base)

    def subset(self, seeds: Sequence[int]) -> "SeedEnsemble":
        index = {s: i for i, s in enumerate(self.seeds)}
        return SeedEnsemble([self.agents[index[s]] for s in seeds], list(seeds), self.config)

    # -- 결합 규칙 ------------------------------------------------------------
    def q_matrix(self, state: np.ndarray) -> np.ndarray:
        """(K, A) 행렬. k행은 시드 k 모델의 Q_k(s, ·)."""
        state = np.asarray(state, dtype=np.float32)
        if state.shape != (self.state_dim,) or not np.isfinite(state).all():
            raise ValueError(f"state must be a finite vector of shape ({self.state_dim},)")
        tensor = torch.from_numpy(state)
        with torch.no_grad():
            rows = [agent.policy_network(tensor).numpy() for agent in self.agents]
        return np.stack(rows).astype(np.float64)

    def _smallest_weight(self, candidates: Iterable[int]) -> int:
        return min(candidates, key=lambda a: (self.action_values[a], a))

    def decide(self, state: np.ndarray, rule: str = "qa", seed: int | None = None) -> EnsembleDecision:
        if rule not in RULES:
            raise ValueError(f"rule must be one of {RULES}")
        q = self.q_matrix(state)
        model_actions = tuple(int(row.argmax()) for row in q)
        votes = tuple(int(v) for v in np.bincount(model_actions, minlength=self.action_dim))

        if rule == "single":
            if seed is None:
                raise ValueError("single rule needs a seed.")
            action = model_actions[self.seeds.index(int(seed))]
        elif rule == "mv":
            # 식 (2): 최다 득표 행동들 중 목표 비중이 가장 작은 행동
            top = max(votes)
            action = self._smallest_weight(a for a, v in enumerate(votes) if v == top)
        else:
            # 식 (3): 행동별 Q값 평균의 최댓값
            mean_q = q.mean(axis=0)
            best = mean_q.max()
            action = self._smallest_weight(a for a, v in enumerate(mean_q) if v == best)

        return EnsembleDecision(
            action=int(action),
            target_weight=self.action_values[action],
            rule=rule,
            q_values=q,
            model_actions=model_actions,
            votes=votes,
        )

    def decider(self, rule: str = "qa", seed: int | None = None):
        """backtester.run_backtest(decide=...) 에 넘길 함수."""
        return lambda state: self.decide(state, rule, seed).action

    # -- 실시간 상태 구성 -------------------------------------------------------
    @property
    def min_candles(self) -> int:
        """피처 준비(MA120 = 120행) + 상태 창(window) 에 필요한 최소 완결 일봉 수."""
        return 120 + self.window - 1

    def live_state(self, ohlcv: pd.DataFrame, position_ratio: float) -> np.ndarray:
        """완결된 일봉(오래된 → 최신)과 현재 보유 비중으로 학습 때와 같은 상태벡터를 만든다.

        TradingEnv._get_observation 과 같은 순서: 최근 window일 × 피처(행 우선) + 보유비중.
        """
        features = make_features(ohlcv, selected_features=self.market_features)
        if len(features) < self.window:
            raise ValueError(
                f"완결 일봉이 부족합니다 (피처 {len(features)}행 < 창 {self.window}행)."
            )
        market = (
            features[self.market_features]
            .to_numpy(dtype=np.float32)[-self.window:]
            .reshape(-1)
        )
        if not np.isfinite(market).all():
            raise ValueError("시장 피처에 유한하지 않은 값이 있습니다.")
        ratio = float(np.clip(position_ratio, 0.0, 1.0))
        return np.concatenate([market, np.array([ratio], dtype=np.float32)])
