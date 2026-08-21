"""강화학습 정책 연결 지점.

나중에 학습한 DQN / A2C / PPO 모델을 붙일 때는 이 파일만 건드리면 된다.

    class MyPPOPolicy(Policy):
        def __init__(self, ckpt): self.net = torch.load(ckpt); self.net.eval()
        def act(self, obs): ...  # PolicyOutput 반환

    register_policy("ppo-ensemble-v1", MyPPOPolicy("runs/ppo.pt"))

상태벡터(Observation)는 연구 계획에서 정한 구성을 그대로 따른다.
OHLCV 정규화 + 기술적 지표 + 뉴스 감성 스칼라 + 에이전트 상태변수.
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.brokers.base import Candle


# --------------------------------------------------------------------------
# 관측 / 행동
# --------------------------------------------------------------------------
@dataclass
class Observation:
    symbol: str
    candles: list[Candle]          # 최근 N일 일봉 (오래된 → 최신)
    price: float                   # 현재가
    cash_ratio: float              # 현금 / 총자산
    position_ratio: float          # 해당 종목 평가액 / 총자산
    unrealized_pct: float          # 해당 종목 평가손익률(%)
    sentiment: float = 0.0         # KR-FinBert-SC 극성 스칼라 s_t ∈ [-1, 1]
    features: dict[str, float] = field(default_factory=dict)  # 기술적 지표


@dataclass
class PolicyOutput:
    action: str                    # "buy" | "hold" | "sell"
    confidence: float              # 0~1
    q_values: dict[str, float]     # {"buy":.., "hold":.., "sell":..}
    reason: str = ""


class Policy(ABC):
    """모든 정책이 구현해야 하는 계약."""

    name: str = "policy"

    @abstractmethod
    def act(self, obs: Observation) -> PolicyOutput: ...


# --------------------------------------------------------------------------
# 기술적 지표 (상태벡터 구성용)
# --------------------------------------------------------------------------
def compute_features(candles: list[Candle]) -> dict[str, float]:
    closes = [c.close for c in candles]
    if len(closes) < 30:
        return {}

    def sma(n: int) -> float:
        return sum(closes[-n:]) / n

    def ema(n: int) -> float:
        k = 2 / (n + 1)
        v = closes[-n]
        for p in closes[-n + 1:]:
            v = p * k + v * (1 - k)
        return v

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-14:] if d > 0]
    losses = [-d for d in deltas[-14:] if d < 0]
    avg_gain = sum(gains) / 14 if gains else 0.0
    avg_loss = sum(losses) / 14 if losses else 1e-9
    rsi = 100 - 100 / (1 + avg_gain / avg_loss)

    macd = ema(12) - ema(26)
    mean20 = sma(20)
    std20 = math.sqrt(sum((c - mean20) ** 2 for c in closes[-20:]) / 20)
    bb_pos = (closes[-1] - mean20) / (2 * std20) if std20 else 0.0

    rets = [deltas[i] / closes[i] for i in range(-20, -1)]
    volatility = math.sqrt(sum(r * r for r in rets) / len(rets)) * math.sqrt(252) * 100

    return {
        "sma5": sma(5),
        "sma20": mean20,
        "sma60": sma(60) if len(closes) >= 60 else mean20,
        "rsi14": rsi,
        "macd": macd,
        "bb_pos": bb_pos,
        "volatility": volatility,
        "momentum": (closes[-1] / closes[-10] - 1) * 100 if len(closes) >= 10 else 0.0,
    }


# --------------------------------------------------------------------------
# 베이스라인 정책 (모델 연결 전 임시)
# --------------------------------------------------------------------------
class HeuristicPolicy(Policy):
    """이동평균 교차 + RSI + 감성 점수를 섞은 규칙 기반 임시 정책.

    학습된 강화학습 모델이 붙기 전까지 파이프라인 전체를 돌려 보기 위한 것으로,
    성능 기준선(baseline) 이상의 의미는 없다.
    """

    name = "heuristic-baseline"

    def act(self, obs: Observation) -> PolicyOutput:
        f = obs.features or compute_features(obs.candles)
        if not f:
            return PolicyOutput("hold", 0.0, {"buy": 0, "hold": 1, "sell": 0}, "데이터 부족")

        score = 0.0
        notes: list[str] = []

        if f["sma5"] > f["sma20"]:
            score += 0.9
            notes.append("5일선이 20일선 위")
        else:
            score -= 0.9
            notes.append("5일선이 20일선 아래")

        if f["rsi14"] < 32:
            score += 1.1
            notes.append(f"RSI {f['rsi14']:.0f} 과매도")
        elif f["rsi14"] > 70:
            score -= 1.1
            notes.append(f"RSI {f['rsi14']:.0f} 과매수")

        score += max(-0.8, min(0.8, -f["bb_pos"] * 0.7))
        score += obs.sentiment * 0.6
        if abs(obs.sentiment) > 0.3:
            notes.append(f"뉴스 감성 {obs.sentiment:+.2f}")

        # 리스크 상태변수 반영: 이미 비중이 크면 추가 매수를 억제
        if obs.position_ratio > 0.4:
            score -= 0.7
            notes.append("보유 비중 과다")
        if obs.unrealized_pct < -7:
            score -= 0.6
            notes.append(f"평가손실 {obs.unrealized_pct:.1f}%")

        q = {
            "buy": round(score, 3),
            "hold": 0.25,
            "sell": round(-score, 3),
        }
        action = max(q, key=q.get)
        spread = max(q.values()) - sorted(q.values())[-2]
        confidence = round(min(0.99, 1 / (1 + math.exp(-spread * 1.6))), 3)
        return PolicyOutput(action, confidence, q, " · ".join(notes[:3]))


class RandomPolicy(Policy):
    """무작위 정책. 성능 비교 대조군."""

    name = "random"

    def act(self, obs: Observation) -> PolicyOutput:
        q = {k: round(random.uniform(-1, 1), 3) for k in ("buy", "hold", "sell")}
        action = max(q, key=q.get)
        return PolicyOutput(action, round(random.uniform(0.4, 0.8), 3), q, "무작위 선택")


# --------------------------------------------------------------------------
# 레지스트리
# --------------------------------------------------------------------------
_REGISTRY: dict[str, Policy] = {}


def register_policy(name: str, policy: Policy) -> None:
    _REGISTRY[name] = policy


def get_policy(name: str) -> Policy:
    return _REGISTRY.get(name, _REGISTRY["heuristic-baseline"])


def list_policies() -> list[str]:
    return list(_REGISTRY)


register_policy("heuristic-baseline", HeuristicPolicy())
register_policy("random", RandomPolicy())
# 학습된 모델은 여기에 추가로 등록한다.
# register_policy("ppo-ensemble-v1", PPOPolicy("checkpoints/ppo_ensemble.pt"))
