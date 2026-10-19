# -*- coding: utf-8 -*-
"""시드 앙상블 DQN 정책 점검.

    cd backend && python scripts/check_seed_ensemble.py

증권사에 접속하지 않는다. 임시 SQLite DB와 내장 시뮬레이터로 다음을 확인한다.

  · 다수결 동점이면 목표 비중이 작은 행동을 고르는가 (논문 식 2)
  · Q값 평균이 모델별 Q의 산술평균 argmax 인가 (식 3)
  · 실시간 상태벡터가 학습 환경(TradingEnv)의 상태와 한 자리도 다르지 않은가
  · 학습된 005930 모델이 있으면: B&H 가 논문 표 2 와 같은가, 정책이 목표 비중을 내는가
  · 러너가 목표 비중을 주문 수량으로 바꾸고, 종목마다 하루 한 번만 리밸런싱하는가
  · 모델이 없는 종목은 주문하지 않는가

실패한 항목이 있으면 종료코드가 1이다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet  # noqa: E402

_TMP = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_TMP}/check_seed_ensemble.db",
    SECRET_KEY="check-seed-" + "x" * 40,
    MASTER_KEY=Fernet.generate_key().decode(),
    KIS_APP_KEY="",
    KIS_APP_SECRET="",
    KIS_MARKET_DATA="false",
    US_MARKET_DATA="false",
    ALLOW_LIVE_TRADING="false",
    FILL_POLL_SECONDS="0",
    AGENT_TICK_SECONDS="3600",
)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import app.models as M  # noqa: E402
from app.agent import policy as P  # noqa: E402
from app.agent import runner as R  # noqa: E402
from app.agent.seed_ensemble.ensemble import SeedEnsemble  # noqa: E402
from app.brokers.base import Candle  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail=None) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok or detail is None else f"  → {detail}"))
    if not ok:
        FAILED.append(name)


# ---------------------------------------------------------------------------
# 1. 결합 규칙
# ---------------------------------------------------------------------------
def _rules_ensemble(q):
    """q_matrix 만 바꿔 끼운 앙상블. 규칙 자체만 본다."""
    ens = SeedEnsemble.__new__(SeedEnsemble)
    ens.seeds = list(range(len(q)))
    ens.action_values = [0.0, 0.5, 1.0]
    ens.action_dim = 3
    ens.q_matrix = lambda state: np.asarray(q, dtype=float)
    return ens


def check_rules() -> None:
    print("\n[1] 결합 규칙 (식 2 · 식 3)")
    # 4개 모델: 0.5 두 표, 1.0 두 표 → 동점 → 작은 비중 0.5
    q = [[0, 2, 1], [0, 3, 1], [0, 1, 2], [0, 1, 5]]
    mv = _rules_ensemble(q).decide(None, "mv")
    check("MV 동점이면 작은 비중", mv.target_weight == 0.5, mv)
    check("MV 득표 집계", mv.votes == (0, 2, 2), mv.votes)
    qa = _rules_ensemble(q).decide(None, "qa")
    check("QA 는 평균 Q 최댓값 (평균: 0, 1.75, 2.25 → 100%)", qa.target_weight == 1.0, qa.mean_q)
    # 3개 모델: 0% 한 표가 Q 차이가 아주 크면 QA 는 다수의 100% 를 뒤집는다 (논문 5.1)
    q = [[10, 0, 0], [0, 0, 1], [0, 0, 1]]
    check("MV 는 다수 100%", _rules_ensemble(q).decide(None, "mv").target_weight == 1.0)
    check("QA 는 확신의 크기를 반영해 0%", _rules_ensemble(q).decide(None, "qa").target_weight == 0.0)
    single = _rules_ensemble(q).decide(None, "single", seed=0)
    check("단일 시드는 그 모델의 argmax", single.target_weight == 0.0)
    check("동의 비율 = 1/3", abs(single.agreement - 1 / 3) < 1e-12, single.agreement)


# ---------------------------------------------------------------------------
# 2. 학습된 모델 (있으면)
# ---------------------------------------------------------------------------
def check_trained(symbol: str = "005930") -> SeedEnsemble | None:
    print(f"\n[2] 학습된 {symbol} 모델")
    root = P.MODELS_DIR / symbol
    try:
        ens = SeedEnsemble.load(root)
    except FileNotFoundError:
        print(f"  skip  {root} 에 모델이 없습니다 (scripts/train_seed_ensemble.py 로 학습)")
        return None
    check("시드 모델을 읽는다", len(ens.seeds) >= 1, ens.seeds)
    check("상태 301차원 · 행동 3개", (ens.state_dim, ens.action_dim) == (301, 3),
          (ens.state_dim, ens.action_dim))

    csv = root / "ohlcv.csv"
    if not csv.exists():
        print("  skip  ohlcv.csv 없음")
        return ens
    from app.agent.seed_ensemble.backtester import run_backtest
    from app.agent.seed_ensemble.features import make_features
    from app.agent.seed_ensemble.preprocessing import clean_ohlcv, prepare_splits
    from app.agent.seed_ensemble.trading_env import TradingEnv

    ohlcv = clean_ohlcv(pd.read_csv(csv))
    config = dict(ens.config)
    config["data"] = {**config.get("data", {}),
                      "validation_start": "2025-01-01", "split_date": "2026-01-01"}
    features = make_features(ohlcv, selected_features=ens.market_features)
    test = prepare_splits(features, config)["test"]
    bh = run_backtest(test, config, strategy="buy_and_hold").metrics
    if symbol == "005930" and str(test.index[-1].date()) == "2026-09-11":
        check("B&H 수익률 = 논문 표 2 (115.60%)", round(bh["cumulative_return"] * 100, 2) == 115.60,
              bh["cumulative_return"])
        check("B&H MDD = 논문 표 2 (42.87%)", round(bh["mdd"] * 100, 2) == 42.87, bh["mdd"])

    # 실시간 상태 == 학습 환경 상태 (보유 비중 0, 앞쪽 이력 250행만 주고)
    env = TradingEnv.from_config(test, config)
    obs_env = env.reset()
    decision_date = test.index[env.window - 1]
    upto = ohlcv.loc[:decision_date].tail(P.CANDLE_LOOKBACK).reset_index()
    obs_live = ens.live_state(upto, 0.0)
    gap = float(np.max(np.abs(obs_env - obs_live)))
    check("실시간 상태벡터 = 학습 환경 상태 (최대 차이 < 1e-5)", gap < 1e-5, gap)
    check("두 상태에서 QA 판단이 같다",
          ens.decide(obs_env, "qa").action == ens.decide(obs_live, "qa").action)
    return ens


# ---------------------------------------------------------------------------
# 3. 러너: 목표 비중 → 주문, 하루 한 번
# ---------------------------------------------------------------------------
class _Target:
    name = "check-target"
    candle_lookback = 10

    def __init__(self):
        self.weight = 1.0

    def act(self, obs):
        return P.PolicyOutput(action="buy", confidence=0.2,  # 임계값보다 낮아도 주문돼야 한다
                              q_values={"buy": 0, "hold": 0, "sell": 0},
                              reason="점검", target_weight=self.weight)


def check_runner() -> None:
    print("\n[3] 러너 — 목표 비중 리밸런싱")
    target = _Target()
    P.register_policy("check-target", target)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        u = M.User(email="seed@kairo.dev", name="점검", password_hash="x")
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(M.CashAccount(user_id=u.id, env=M.Env.paper, market=M.Market.kr))
        cfg = M.AgentConfig(
            user_id=u.id, env=M.Env.paper, market=M.Market.kr, enabled=True,
            model_name="check-target", universe="005930",
            trading_start="00:00", trading_end="23:59", risk_ack_at=R.utcnow(),
            order_cooldown_seconds=0, max_daily_orders=20,
            max_position_pct=100.0, max_order_amount=1e12, confidence_threshold=0.55,
        )
        db.add(cfg)
        db.commit()

        def orders():
            return db.query(M.Order).filter_by(user_id=u.id, source="agent").all()

        first = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("목표 100% → 매수 주문", len(orders()) == 1 and orders()[0].side == M.Side.buy,
              [r["reason"] for r in first])
        check("신뢰도 임계값은 목표 비중 정책에 적용하지 않는다", first[0]["executed"], first[0]["reason"])
        bal = R.get_broker(db, u.id, M.Env.paper, M.Market.kr).get_balance()
        w = bal.holdings_value / bal.total_equity
        check("체결 후 비중이 100%에 가깝다 (정수 주식)", 0.95 < w <= 1.0, w)

        second = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("같은 날 두 번째 틱은 주문하지 않는다", len(orders()) == 1, len(orders()))
        check("사유: 오늘 리밸런싱 완료", "오늘 리밸런싱 완료" in second[0]["reason"], second[0]["reason"])

        # 날이 바뀐 것으로 치고 목표 50% → 절반 매도
        R._rebalanced_on.clear()
        for o in orders():
            o.created_at = o.created_at - timedelta(days=2)
        db.commit()
        target.weight = 0.5
        held_before = bal.holdings[0].quantity
        third = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        sells = [o for o in orders() if o.side == M.Side.sell]
        check("다음 날 목표 50% → 매도", len(sells) == 1, [r["reason"] for r in third])
        bal = R.get_broker(db, u.id, M.Env.paper, M.Market.kr).get_balance()
        w = bal.holdings_value / bal.total_equity
        # 매도세·수수료만큼 자산이 줄어 50%를 아주 조금 넘을 수 있다 (학습 환경도 같다)
        check("매도 후 비중이 50% 근처", 0.45 < w < 0.51, w)
        check("매도 수량 = 보유 - floor(0.5 × 자산 ÷ 가격)",
              sells and sells[0].quantity == held_before - bal.holdings[0].quantity)
        check("신호 기록의 행동이 매도", third[0]["action"] == "sell", third[0]["action"])

        # 다음 날 목표 0% → 전량 매도, 그다음 날도 0% → 보유 0주 = 목표 0주 라 주문 없음
        def next_day():
            R._rebalanced_on.clear()
            for o in orders():
                o.created_at = o.created_at - timedelta(days=2)
            db.commit()

        next_day()
        target.weight = 0.0
        R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        bal = R.get_broker(db, u.id, M.Env.paper, M.Market.kr).get_balance()
        check("목표 0% → 전량 매도", not bal.holdings, bal.holdings)
        next_day()
        n = len(orders())
        fourth = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("목표 수량 = 보유 수량이면 주문 없음", len(orders()) == n, fourth[0]["reason"])
        check("그때 신호는 관망으로 남는다", fourth[0]["action"] == "hold", fourth[0]["action"])
        check("그날은 다시 계산하지 않는다",
              "오늘 리밸런싱 완료" in R.step_once(db, u.id, M.Env.paper, M.Market.kr)[0]["reason"])

        # 종목당 최대 비중 한도는 그대로 적용
        R._rebalanced_on.clear()
        for o in orders():
            o.created_at = o.created_at - timedelta(days=2)
        cfg.max_position_pct = 30.0
        db.commit()
        target.weight = 1.0
        R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        bal = R.get_broker(db, u.id, M.Env.paper, M.Market.kr).get_balance()
        w = bal.holdings_value / bal.total_equity
        check("최대 비중 30% 한도가 목표 100%를 자른다", w <= 0.30 + 1e-9, w)

        # 실제 정책: 모델 없는 종목은 관망
        cfg.model_name = "dqn-seed-ensemble-qa"
        cfg.universe = "035720"
        R._rebalanced_on.clear()
        db.commit()
        n = len(orders())
        res = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("모델 없는 종목은 주문하지 않는다", len(orders()) == n and res[0]["action"] == "hold",
              res[0]["reason"])
        check("사유에 '학습된 모델 없음'", "학습된 모델 없음" in res[0]["reason"], res[0]["reason"])
    finally:
        db.close()


def check_live_policy(ens: SeedEnsemble | None) -> None:
    print("\n[4] 실제 정책 act() — 005930")
    if ens is None:
        print("  skip  005930 모델 없음")
        return
    today = date.today()
    base = [
        Candle(date=(today - timedelta(days=400 - i)).isoformat(), open=100 + i * 0.1,
               high=101 + i * 0.1, low=99 + i * 0.1, close=100.5 + i * 0.1,
               volume=1_000_000 + 10 * i)
        for i in range(400)
    ]
    # 오늘 날짜 봉(장중)이 섞여 있어도 결과가 같아야 한다
    with_today = base + [Candle(today.isoformat(), 1, 999, 1, 999, 1)]
    obs = dict(symbol="005930", price=140.0, cash_ratio=1.0, position_ratio=0.0,
               unrealized_pct=0.0, quantity=0, equity=10_000_000)
    for name in ("dqn-seed-ensemble-qa", "dqn-seed-ensemble-mv", f"dqn-seed-{ens.seeds[0]}"):
        a = P.get_policy(name).act(P.Observation(candles=base, **obs))
        b = P.get_policy(name).act(P.Observation(candles=with_today, **obs))
        check(f"{name}: 목표 비중을 낸다", a.target_weight in (0.0, 0.5, 1.0), a.reason)
        check(f"{name}: 장중 오늘 봉은 무시한다", (a.target_weight, a.q_values) == (b.target_weight, b.q_values))
    short = P.get_policy("dqn-seed-ensemble-qa").act(P.Observation(candles=base[-100:], **obs))
    check("일봉이 139개보다 적으면 관망", short.action == "hold" and short.target_weight is None,
          short.reason)
    check("예전 정책 이름은 기본 정책으로", P.get_policy("heuristic-baseline").name == P.DEFAULT_POLICY)


if __name__ == "__main__":
    check_rules()
    trained = check_trained()
    check_runner()
    check_live_policy(trained)
    print()
    if FAILED:
        print(f"실패 {len(FAILED)}건: {FAILED}")
        sys.exit(1)
    print("모두 통과했습니다.")
