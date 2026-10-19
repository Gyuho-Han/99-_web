"""강화학습 정책 연결 지점 — 시드 앙상블 DQN (논문 구현).

이전의 규칙 기반 임시 정책(HeuristicPolicy · RandomPolicy)을 걷어 내고, 논문
「시드 앙상블을 통한 DQN 주식 비중 조절의 성과 및 안정성 개선」의 정책으로 바꿨다.

  dqn-seed-ensemble-qa   Q값 평균 앙상블 (식 3)  ← 기본값. 논문에서 세 종목 모두 B&H보다
                                                   수익률은 높고 MDD는 낮았던 규칙
  dqn-seed-ensemble-mv   다수결 앙상블 (식 2, 동점이면 작은 비중)
  dqn-seed-<k>           단일 시드 DQN (논문의 비교 기준)

정책은 '매수/매도'가 아니라 **목표 주식 비중** w ∈ {0, 0.5, 1} 을 낸다.
러너(runner.py)가 현재 보유 수량과의 차이를 주문 수량으로 바꾼다.

모델은 종목별로 학습한다. backend/models/seed_ensemble/<종목코드>/seed-<k>/dqn_model.pth
가 없는 종목은 관망(hold)으로 남기고 주문하지 않는다. 학습은
`python -m scripts.train_seed_ensemble --symbol <종목코드>` 로 한다.

상태벡터는 학습 때와 같다: 완결된 일봉으로 만든 시장 특성 15개 × 최근 20일 + 보유 비중.
장중의 미완결 오늘 일봉은 넣지 않는다(논문: t일 종가까지 관찰 → t+1일 시가에 체결).
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.brokers.base import Candle

log = logging.getLogger("kairo.policy")

MODELS_DIR = Path(__file__).resolve().parents[2] / "models" / "seed_ensemble"
PAPER_SEEDS = (1, 7, 21, 42, 100)
DEFAULT_POLICY = "dqn-seed-ensemble-qa"
# 피처 준비(MA120)와 20일 창에 139개가 필요하다. RSI가 지수평균이라 앞쪽 이력이
# 길수록 학습 때 값과 같아지므로 넉넉히 받는다 (250개면 차이가 1e-7 수준).
CANDLE_LOOKBACK = 250


# --------------------------------------------------------------------------
# 관측 / 행동
# --------------------------------------------------------------------------
@dataclass
class Observation:
    symbol: str
    candles: list[Candle]          # 최근 N일 일봉 (오래된 → 최신). 오늘 미완결 봉이 섞일 수 있다
    price: float                   # 현재가
    cash_ratio: float              # 현금 / 총자산
    position_ratio: float          # 해당 종목 평가액 / 총자산 (현재가 기준)
    unrealized_pct: float          # 해당 종목 평가손익률(%)
    sentiment: float = 0.0         # 논문 정책은 쓰지 않는다 (상태에 감성 피처 없음)
    features: dict[str, float] = field(default_factory=dict)
    quantity: int = 0              # 해당 종목 보유 수량
    equity: float = 0.0            # 총자산 (현재가 기준)


@dataclass
class PolicyOutput:
    action: str                    # "buy" | "hold" | "sell"
    confidence: float              # 0~1. 앙상블은 선택 행동에 동의한 모델 비율
    q_values: dict[str, float]     # {"buy":.., "hold":.., "sell":..}
    reason: str = ""
    # 목표 비중 정책이면 0~1. None 이면 action 만 보고 주문한다(예전 방식).
    target_weight: float | None = None


class Policy(ABC):
    """모든 정책이 구현해야 하는 계약."""

    name: str = "policy"
    candle_lookback: int = CANDLE_LOOKBACK

    @abstractmethod
    def act(self, obs: Observation) -> PolicyOutput: ...


# --------------------------------------------------------------------------
# 시드 앙상블 DQN
# --------------------------------------------------------------------------
class _EnsembleCache:
    """종목별 모델 묶음을 한 번만 읽는다. 파일이 새로 생기면 다음 호출에서 읽는다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._loaded: dict[str, tuple[tuple, object]] = {}

    def _fingerprint(self, symbol: str) -> tuple:
        files = sorted((self.root / symbol).glob("seed-*/dqn_model.pth"))
        return tuple((p.parent.name, p.stat().st_mtime_ns) for p in files)

    def get(self, symbol: str):
        from app.agent.seed_ensemble.ensemble import SeedEnsemble

        stamp = self._fingerprint(symbol)
        if not stamp:
            return None
        with self._lock:
            hit = self._loaded.get(symbol)
            if hit and hit[0] == stamp:
                return hit[1]
            ensemble = SeedEnsemble.load(self.root / symbol)
            self._loaded[symbol] = (stamp, ensemble)
            log.info("시드 앙상블 모델을 읽었습니다: %s seeds=%s", symbol, ensemble.seeds)
            return ensemble


_cache = _EnsembleCache(MODELS_DIR)


def completed_candles(candles: list[Candle], today: date | None = None) -> list[Candle]:
    """오늘 날짜 봉(장중이면 미완결)을 뺀다. 결정은 직전 거래일 종가까지의 정보로 한다."""
    cutoff = (today or date.today()).isoformat()
    return [c for c in candles if c.date < cutoff]


def _hold(reason: str) -> PolicyOutput:
    return PolicyOutput("hold", 0.0, {"buy": 0.0, "hold": 0.0, "sell": 0.0}, reason)


class SeedEnsemblePolicy(Policy):
    """rule: 'qa' | 'mv' | 'single'(seed 지정)."""

    def __init__(self, rule: str, seed: int | None = None, cache: _EnsembleCache = _cache):
        self.rule = rule
        self.seed = seed
        self.cache = cache
        self.name = (
            f"dqn-seed-{seed}" if rule == "single" else f"dqn-seed-ensemble-{rule}"
        )

    def act(self, obs: Observation) -> PolicyOutput:
        try:
            ensemble = self.cache.get(obs.symbol)
        except ImportError as e:
            return _hold(f"시드 앙상블 의존성 미설치 ({e.name}) — pip install -r requirements.txt")
        except Exception as e:  # noqa: BLE001 — 체크포인트 문제는 주문 대신 관망으로
            log.exception("시드 앙상블 모델 로드 실패 %s", obs.symbol)
            return _hold(f"모델 로드 실패: {e}")
        if ensemble is None:
            return _hold(f"{obs.symbol} 학습된 모델 없음 (models/seed_ensemble/{obs.symbol})")
        if self.rule == "single" and self.seed not in ensemble.seeds:
            return _hold(f"{obs.symbol} seed-{self.seed} 모델 없음")

        import pandas as pd

        from app.agent.seed_ensemble.ensemble import RULE_LABEL

        candles = completed_candles(obs.candles)
        if len(candles) < ensemble.min_candles:
            return _hold(f"완결 일봉 부족 ({len(candles)} < {ensemble.min_candles})")
        last_close = candles[-1].close

        # 보유 비중은 학습과 같이 '직전 종가' 기준으로 다시 잰다 (env: shares × close[t] / asset).
        position = obs.position_ratio
        if obs.equity > 0 and last_close > 0:
            held_now = obs.position_ratio * obs.equity   # 잔고 평가액 (총자산과 같은 가격 기준)
            held_prev = obs.quantity * last_close
            asset_prev = obs.equity - held_now + held_prev
            if asset_prev > 0:
                position = held_prev / asset_prev

        frame = pd.DataFrame(
            [
                {
                    "date": c.date,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in candles
            ]
        )
        try:
            state = ensemble.live_state(frame, position)
            decision = ensemble.decide(state, self.rule, self.seed)
        except ValueError as e:
            return _hold(str(e))

        weights = ensemble.action_values
        q = (
            decision.q_values[ensemble.seeds.index(self.seed)]
            if self.rule == "single"
            else decision.mean_q
        )
        q_by_weight = dict(zip(weights, (float(v) for v in q)))
        target = decision.target_weight
        if target > position + 1e-9:
            action = "buy"
        elif target < position - 1e-9:
            action = "sell"
        else:
            action = "hold"

        votes = " ".join(f"{w:.0%}:{v}" for w, v in zip(weights, decision.votes))
        reason = (
            f"{RULE_LABEL[self.rule]} 목표비중 {target:.0%} (현재 {position:.0%}) · "
            f"득표 {votes} · 기준일 {candles[-1].date}"
        )
        return PolicyOutput(
            action=action,
            # 선택된 비중과 같은 비중을 고른 시드 모델의 비율 (단일 시드도 같은 정의)
            confidence=round(decision.agreement, 3),
            # 화면의 세 칸(q_buy · q_hold · q_sell)에 Q(100%) · Q(50%) · Q(0%) 를 싣는다.
            q_values={
                "buy": round(q_by_weight.get(1.0, 0.0), 6),
                "hold": round(q_by_weight.get(0.5, 0.0), 6),
                "sell": round(q_by_weight.get(0.0, 0.0), 6),
            },
            reason=reason,
            target_weight=target,
        )


# --------------------------------------------------------------------------
# 레지스트리
# --------------------------------------------------------------------------
_REGISTRY: dict[str, Policy] = {}


def register_policy(name: str, policy: Policy) -> None:
    _REGISTRY[name] = policy


def get_policy(name: str) -> Policy:
    # 예전 설정값(heuristic-baseline, ppo-ensemble-v0 등)은 기본 정책으로 돌린다.
    return _REGISTRY.get(name, _REGISTRY[DEFAULT_POLICY])


def list_policies() -> list[str]:
    return list(_REGISTRY)


register_policy("dqn-seed-ensemble-qa", SeedEnsemblePolicy("qa"))
register_policy("dqn-seed-ensemble-mv", SeedEnsemblePolicy("mv"))
for _seed in PAPER_SEEDS:
    register_policy(f"dqn-seed-{_seed}", SeedEnsemblePolicy("single", _seed))
