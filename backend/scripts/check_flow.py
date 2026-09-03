# -*- coding: utf-8 -*-
"""연결 플로우 점검.

    cd backend && python scripts/check_flow.py

증권사에 실제로 접속하지 않는다. 임시 SQLite DB를 하나 만들어 다음을 확인한다.

  · 자격증명이 (환경, 시장) 조합마다 따로 저장되는가
  · 리스크 한도를 확인하기 전에는 자동매매가 켜지지 않는가
  · 실계좌 주문과 자동매매 가동이 ALLOW_LIVE_TRADING 으로 막히는가
  · 비상정지가 모든 조합의 자동매매를 끄는가
  · 미체결 주문이 체결 조회 결과대로 갱신되는가
  · 오래된 DB에 risk_ack_at 컬럼이 자동으로 붙는가
  · 계좌를 붙여도 시세는 서버 공용 소스에서 오는가
  · 증권사 쪽 실패가 500이 아니라 502로 나가는가
  · 같은 주문이 매 틱 반복해서 나가지 않는가
  · 전송에 실패한 주문이 미체결인 척 쌓이지 않는가
  · 거래 시각이 UTC임을 명시해서 나가는가
  · 포트폴리오가 보유·청산·실현손익을 맞게 집계하는가

이 파일들을 손본 뒤에 한 번 돌려 보면 된다. 실패한 항목이 있으면 종료코드가 1이다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 실행 위치와 무관하게 backend/ 를 import 경로에 둔다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet  # noqa: E402

# 설정을 읽기 전에 환경을 고정한다. backend/.env 의 실제 앱키를 쓰지 않도록
# 시세 소스를 끄고, DB도 임시 파일로 돌린다.
_TMP = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_TMP}/check_flow.db",
    SECRET_KEY="check-flow-" + "x" * 40,
    MASTER_KEY=Fernet.generate_key().decode(),
    KIS_APP_KEY="",
    KIS_APP_SECRET="",
    KIS_MARKET_DATA="false",
    US_MARKET_DATA="false",
    ALLOW_LIVE_TRADING="false",
    FILL_POLL_SECONDS="0",
    AGENT_TICK_SECONDS="3600",
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models as M  # noqa: E402
from app.brokers import market as market_source  # noqa: E402
from app.brokers import overlay as overlay_mod  # noqa: E402
from app.brokers.base import (  # noqa: E402
    Balance, BrokerAdapter, BrokerError, Candle, Fill, OrderResult, Quote,
)
from app.brokers.factory import get_broker  # noqa: E402
from app.core.security import encrypt_secret  # noqa: E402
from app.db.migrate import ensure_columns  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import fills as F  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, extra: object = "") -> None:
    print(("  ok    " if ok else "  실패  ") + label + ("" if ok else f"   ← {extra}"))
    if not ok:
        FAILS.append(label)


# ---------------------------------------------------------------------------
# 1. API 플로우
# ---------------------------------------------------------------------------
def check_api() -> None:
    print("\n[1] 연결 · 게이트 · 비상정지")
    with TestClient(app) as c:
        r = c.post(
            "/api/auth/signup",
            json={"email": "check-flow@kairo.dev", "name": "점검", "password": "kairo1234"},
        )
        check("가입", r.status_code in (200, 201), r.text[:200])
        H = {"authorization": f"Bearer {r.json()['access_token']}"}

        # 자격증명이 없으면 시뮬레이터가 처리한다
        r = c.post(
            "/api/orders",
            params={"env": "paper", "market": "kr"},
            headers=H,
            json={"symbol": "005930", "side": "buy", "quantity": 1, "price": 0,
                  "order_type": "market"},
        )
        check("모의투자 수동주문", r.status_code == 201, f"{r.status_code} {r.text[:200]}")

        d = c.get("/api/connection/status", params={"env": "paper", "market": "kr"},
                  headers=H).json()
        check("연결 단계 4개", len(d["steps"]) == 4, d.get("steps"))
        check("등록 전이므로 첫 단계 미완료", d["steps"][0]["done"] is False)
        check("모의투자는 잠기지 않음", d["locked"] is False)

        d = c.get("/api/connection/status", params={"env": "live", "market": "us"},
                  headers=H).json()
        check("실계좌는 잠김", d["locked"] is True and bool(d["lock_reason"]), d)
        check("네 조합 현황", len(d["matrix"]) == 4, d.get("matrix"))

        # 시장별로 따로 저장되는가 — 이 축이 빠지면 미국 계좌가 국내 자리를 덮어쓴다
        for mkt in ("kr", "us"):
            r = c.put("/api/credentials", headers=H, json={
                "broker": "kis", "env": "paper", "market": mkt,
                "app_key": "PSCHECKFLOW01", "app_secret": "SECRETCHECKFLOW",
                "account_no": "50123456-01",
            })
            check(f"자격증명 저장 ({mkt})", r.status_code == 200, r.text[:200])
        rows = c.get("/api/credentials", headers=H).json()
        check("국내·미국이 각각 남음", sorted(x["market"] for x in rows) == ["kr", "us"], rows)
        check("평문 키가 응답에 없음", all("app_key" not in x for x in rows))

        r = c.patch("/api/agent/config", params={"env": "paper", "market": "kr"},
                    headers=H, json={"enabled": True})
        check("한도 확인 전 가동 차단", r.status_code == 428, f"{r.status_code} {r.text[:160]}")

        r = c.patch("/api/agent/config", params={"env": "paper", "market": "kr"},
                    headers=H, json={"enabled": True, "risk_ack": True})
        cfg = r.json() if r.status_code == 200 else {}
        check("한도 확인 후 가동", r.status_code == 200 and cfg.get("enabled") is True, r.text[:200])
        check("확인 시각 기록", cfg.get("risk_ack_at") is not None, cfg)
        check("risk_ack 가 설정으로 새지 않음", "risk_ack" not in cfg, cfg)

        r = c.patch("/api/agent/config", params={"env": "live", "market": "kr"},
                    headers=H, json={"enabled": True, "risk_ack": True})
        check("실계좌 자동매매 잠금", r.status_code == 423, f"{r.status_code} {r.text[:160]}")

        r = c.post("/api/orders", params={"env": "live", "market": "kr"}, headers=H,
                   json={"symbol": "005930", "side": "buy", "quantity": 1, "price": 70000,
                         "order_type": "limit"})
        check("실계좌 수동주문 잠금", r.status_code == 423, f"{r.status_code} {r.text[:160]}")

        r = c.post("/api/agent/step",
                   params={"env": "live", "market": "kr", "dry_run": "true"}, headers=H)
        check("실계좌 미리보기는 허용", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
        r = c.post("/api/agent/step",
                   params={"env": "live", "market": "kr", "dry_run": "false"}, headers=H)
        check("실계좌 실행은 차단", r.status_code == 423, f"{r.status_code} {r.text[:160]}")

        r = c.post("/api/agent/panic", headers=H)
        check("비상정지", r.status_code == 200 and r.json()["disabled"] >= 1, r.text[:200])
        r = c.get("/api/agent/config", params={"env": "paper", "market": "kr"}, headers=H)
        check("비상정지 후 정지 상태", r.json()["enabled"] is False, r.json())

        done = {
            s["key"]: s["done"]
            for s in c.get("/api/connection/status", params={"env": "paper", "market": "kr"},
                           headers=H).json()["steps"]
        }
        check("등록 단계 완료 반영", done["register"] is True, done)
        check("연결 테스트는 아직 미완료", done["verify"] is False, done)
        check("한도 확인 완료 반영", done["risk"] is True, done)
        check("가동 단계 정지 반영", done["run"] is False, done)


# ---------------------------------------------------------------------------
# 2. 체결 폴링
# ---------------------------------------------------------------------------
def check_fills() -> None:
    print("\n[2] 미체결 주문 체결 반영")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        u = M.User(email="fills@kairo.dev", name="점검", password_hash="x")
        db.add(u)
        db.commit()
        db.refresh(u)
        # 개인 자격증명이 있어야 "실계좌 조합"으로 인식된다. 네트워크는 타지 않는다.
        db.add(M.BrokerCredential(
            user_id=u.id, broker="kis", env=M.Env.paper, market=M.Market.kr,
            app_key_enc=encrypt_secret("k"), app_secret_enc=encrypt_secret("s"),
            account_no_enc=encrypt_secret("50123456-01"), is_active=True))

        def order(oid: str):
            o = M.Order(user_id=u.id, env=M.Env.paper, market=M.Market.kr,
                        broker_order_id=oid, symbol="005930", name="삼성전자",
                        side=M.Side.buy, order_type="limit", quantity=10, price=70000)
            db.add(o)
            return o

        full, part, canceled, quiet, missing = (order(f"000000000{i}") for i in range(1, 6))
        db.commit()

        answer = {
            "0000000001": Fill("0000000001", 10, 10, 70100.0, False),
            "0000000002": Fill("0000000002", 10, 4, 70050.0, False),
            "0000000003": Fill("0000000003", 10, 0, 0.0, True),
            "0000000004": Fill("0000000004", 10, 0, 0.0, False),
            # 0000000005 는 조회 구간 밖이라 응답에 없다
        }
        asked: list[list[str]] = []

        class FakeBroker:
            def get_fills(self, ids):
                asked.append(sorted(ids))
                return {k: v for k, v in answer.items() if k in ids}

        original = F.get_broker
        F.get_broker = lambda *a, **k: FakeBroker()
        try:
            changed = F.sync_pending_orders(db)
            for o in (full, part, canceled, quiet, missing):
                db.refresh(o)

            check("갱신 건수", changed == 3, changed)
            check("전량 체결 → 체결완료",
                  full.status == M.OrderStatus.filled and full.filled_quantity == 10, full.status)
            check("체결 평균단가 반영", full.filled_price == 70100.0, full.filled_price)
            check("체결 시각 기록", full.filled_at is not None)
            check("일부 체결 → 부분체결",
                  part.status == M.OrderStatus.partial and part.filled_quantity == 4, part.status)
            check("한 주도 못 채우고 취소 → 취소",
                  canceled.status == M.OrderStatus.canceled, canceled.status)
            check("변화 없는 주문은 그대로", quiet.status == M.OrderStatus.pending, quiet.status)
            check("응답에 없는 주문은 건드리지 않음",
                  missing.status == M.OrderStatus.pending, missing.status)
            check("한 번의 조회로 다섯 건을 묶어 물었다", len(asked[0]) == 5, asked[0])
            check("다시 돌려도 바뀌지 않음", F.sync_pending_orders(db) == 0)
            check("끝난 주문은 다시 조회하지 않음",
                  asked[-1] == ["0000000002", "0000000004", "0000000005"], asked[-1])

            db.query(M.BrokerCredential).delete()
            db.commit()
            check("개인 자격증명이 없으면 조회하지 않음", F.sync_pending_orders(db) == 0)
        finally:
            F.get_broker = original
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. 컬럼 마이그레이션
# ---------------------------------------------------------------------------
def check_migration() -> None:
    print("\n[3] 예전 DB 자동 보정")
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE agent_configs DROP COLUMN risk_ack_at'))
    check("빠진 컬럼을 붙인다", ensure_columns(engine) == ["agent_configs.risk_ack_at"])
    check("이미 있으면 아무것도 하지 않는다", ensure_columns(engine) == [])




# ---------------------------------------------------------------------------
# 4. 시세는 계좌와 분리되는가
#
# KIS 모의투자 도메인은 시세조회를 제대로 지원하지 않는다. 계좌를 붙였다고
# 시세까지 그 도메인으로 보내면 현재가·일봉이 500으로 깨진다.
# ---------------------------------------------------------------------------
class _FakeAccount(BrokerAdapter):
    name = "fake-account"
    currency = "KRW"

    def __init__(self):
        self.quote_calls = 0
        self.candle_calls = 0
        self.balance_calls = 0

    def verify(self):
        return True, "ok"

    def get_quote(self, symbol):
        self.quote_calls += 1
        raise BrokerError("모의투자 도메인 시세조회 500")

    def get_candles(self, symbol, days=120):
        self.candle_calls += 1
        raise BrokerError("모의투자 도메인 일봉조회 500")

    def get_balance(self):
        self.balance_calls += 1
        return Balance(cash=1_000_000.0)

    def place_order(self, symbol, side, quantity, price=0.0, order_type="limit"):
        return OrderResult(ok=True, broker_order_id="X1", message="접수")

    def cancel_order(self, broker_order_id):
        return OrderResult(ok=True, broker_order_id=broker_order_id)


def check_quote_source() -> None:
    print("\n[4] 시세 · 계좌 분리")
    from datetime import datetime as _dt

    shared = Quote(symbol="005930", name="삼성전자", price=71000, prev_close=70000,
                   open=70500, high=71500, low=70200, volume=1234, ts=_dt.now())
    rows = [Candle(date="2026-09-01", open=1, high=2, low=1, close=2, volume=10)]

    saved = (market_source.get_quote, market_source.get_candles, market_source.status)
    market_source.get_quote = lambda symbol, market=None: shared
    market_source.get_candles = lambda symbol, days=120, market=None: rows
    try:
        account = _FakeAccount()
        broker = overlay_mod.MarketDataBroker(account, M.Market.kr)
        check("현재가는 공용 소스에서 온다", broker.get_quote("005930").price == 71000)
        check("일봉도 공용 소스에서 온다", broker.get_candles("005930", 60) == rows)
        check("계좌 어댑터의 시세 호출은 0회",
              account.quote_calls == 0 and account.candle_calls == 0,
              (account.quote_calls, account.candle_calls))
        check("잔고는 계좌 어댑터로 간다",
              broker.get_balance().cash == 1_000_000.0 and account.balance_calls == 1)
        check("주문도 계좌 어댑터로 간다", broker.place_order("005930", "buy", 1, 70000).ok)

        # 공용 소스가 쿨다운이면 시뮬레이터로 내려가지 않고 실패해야 한다.
        # 실제 계좌가 붙은 채로 가짜 가격에 주문이 나가면 안 되기 때문이다.
        market_source.get_quote = lambda symbol, market=None: None
        market_source.status = lambda market=None: {
            "degraded": True, "retry_in": 42, "last_error": "KIS 500",
        }
        try:
            broker.get_quote("005930")
            check("공용 소스 실패 시 예외", False, "예외가 나지 않았다")
        except BrokerError as e:
            check("공용 소스 실패 시 시뮬레이터로 안 내려간다", "42초" in str(e), str(e))
        check("그래도 계좌 시세는 부르지 않는다", account.quote_calls == 0, account.quote_calls)
    finally:
        market_source.get_quote, market_source.get_candles, market_source.status = saved

    # factory 가 실제로 감싸 주는지
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        u = M.User(email="overlay@kairo.dev", name="점검", password_hash="x")
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(M.BrokerCredential(
            user_id=u.id, broker="kis", env=M.Env.paper, market=M.Market.kr,
            app_key_enc=encrypt_secret("k"), app_secret_enc=encrypt_secret("s"),
            account_no_enc=encrypt_secret("50123456-01"), is_active=True))
        db.commit()

        import app.brokers.factory as factory
        saved_enabled = factory.market_source.is_enabled
        try:
            factory.market_source.is_enabled = lambda market=None: True
            b = get_broker(db, u.id, M.Env.paper, M.Market.kr)
            check("공용 실시세가 있으면 계좌 어댑터를 감싼다",
                  isinstance(b, overlay_mod.MarketDataBroker), type(b).__name__)

            factory.market_source.is_enabled = lambda market=None: False
            b = get_broker(db, u.id, M.Env.paper, M.Market.kr)
            check("공용 실시세가 없으면 계좌 어댑터를 그대로 쓴다",
                  not isinstance(b, overlay_mod.MarketDataBroker), type(b).__name__)
        finally:
            factory.market_source.is_enabled = saved_enabled
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. 증권사 실패가 502로 나가는가
# ---------------------------------------------------------------------------
def check_error_mapping() -> None:
    print("\n[5] 증권사 실패 → 502")
    import httpx as _httpx

    import app.api.routes_trading as rt

    with TestClient(app) as c:
        r = c.post("/api/auth/signup",
                   json={"email": "err@kairo.dev", "name": "점검", "password": "kairo1234"})
        H = {"authorization": f"Bearer {r.json()['access_token']}"}

        class Boom(_FakeAccount):
            pass

        saved = rt.get_broker
        try:
            rt.get_broker = lambda *a, **k: Boom()
            r = c.get("/api/market/quote/005930", params={"env": "paper", "market": "kr"},
                      headers=H)
            check("BrokerError → 502", r.status_code == 502, f"{r.status_code} {r.text[:160]}")
            check("사유가 그대로 실린다", "500" in r.json().get("detail", ""), r.text[:160])

            class Transport(_FakeAccount):
                def get_quote(self, symbol):
                    request = _httpx.Request("GET", "https://openapivts.example/x")
                    raise _httpx.HTTPStatusError(
                        "Server error '500'", request=request,
                        response=_httpx.Response(500, request=request))

            rt.get_broker = lambda *a, **k: Transport()
            r = c.get("/api/market/quote/005930", params={"env": "paper", "market": "kr"},
                      headers=H)
            check("httpx 오류 → 502", r.status_code == 502, f"{r.status_code} {r.text[:160]}")
            check("스택트레이스 대신 짧은 안내",
                  "증권사 서버" in r.json().get("detail", ""), r.text[:200])
        finally:
            rt.get_broker = saved


# ---------------------------------------------------------------------------
# 6. 주문 폭주 방지
#
# 규칙 기반 정책은 조건이 유지되는 한 매 틱 같은 신호를 낸다. 게이트가 없으면
# 루프 주기(기본 5초)마다 같은 매수가 계속 나간다. 실제로 10분 만에 71건이
# 쌓인 적이 있다. 아래 세 개가 그것을 막는다.
# ---------------------------------------------------------------------------
class _AlwaysBuy:
    name = "always-buy"

    def act(self, obs):
        from app.agent.policy import PolicyOutput
        return PolicyOutput(action="buy", confidence=0.99,
                            q_values={"buy": 1.0, "hold": 0.0, "sell": 0.0},
                            reason="점검용 정책")


def check_order_flood() -> None:
    print("\n[6] 주문 폭주 방지")
    from app.agent import runner as R
    from app.agent.policy import register_policy

    register_policy("always-buy", _AlwaysBuy())
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        u = M.User(email="flood@kairo.dev", name="점검", password_hash="x")
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(M.CashAccount(user_id=u.id, env=M.Env.paper, market=M.Market.kr))
        cfg = M.AgentConfig(
            user_id=u.id, env=M.Env.paper, market=M.Market.kr, enabled=True,
            model_name="always-buy", universe="005930",
            trading_start="00:00", trading_end="23:59",
            risk_ack_at=R.utcnow(), order_cooldown_seconds=300, max_daily_orders=20,
        )
        db.add(cfg)
        db.commit()

        def orders():
            return db.query(M.Order).filter_by(user_id=u.id, source="agent").all()

        def reasons(res):
            return " | ".join(r.get("reason") or "" for r in res)

        first = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("첫 틱에 주문이 나간다", len(orders()) == 1, [o.status for o in orders()])
        check("첫 틱은 실행됨", any(r["executed"] for r in first), reasons(first))

        # 시뮬레이터는 즉시 체결하므로 미체결 게이트가 아니라 쿨다운이 잡아야 한다
        second = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("두 번째 틱은 쿨다운에 막힌다", len(orders()) == 1, len(orders()))
        check("차단 사유가 쿨다운", "재주문 대기" in reasons(second), reasons(second))

        # 쿨다운을 풀면 다시 나가고, 미체결이 있으면 다시 막힌다
        cfg.order_cooldown_seconds = 0
        db.add(M.Order(
            user_id=u.id, env=M.Env.paper, market=M.Market.kr, symbol="005930",
            name="삼성전자", side=M.Side.buy, order_type="limit", quantity=1,
            price=70000, status=M.OrderStatus.pending, source="manual",
            broker_order_id="OPEN-1"))
        db.commit()
        third = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("미체결이 있으면 신규 주문을 내지 않는다", len(orders()) == 1, len(orders()))
        check("차단 사유가 미체결", "미체결" in reasons(third), reasons(third))

        # 일일 한도
        db.query(M.Order).filter_by(broker_order_id="OPEN-1").delete()
        cfg.max_daily_orders = 1
        db.commit()
        fourth = R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        check("일일 주문 한도가 걸린다", "일일 주문 건수 한도" in reasons(fourth), reasons(fourth))

        # 전송 실패는 pending 이 아니라 rejected
        cfg.max_daily_orders = 20
        db.commit()

        class _Reject:
            name = "reject"
            currency = "KRW"

            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, k):
                return getattr(self._inner, k)

            def place_order(self, *a, **k):
                from app.brokers.base import OrderResult
                return OrderResult(ok=False, message="모의투자 서버 500")

        saved = R.get_broker
        try:
            R.get_broker = lambda db_, uid, env, mkt: _Reject(saved(db_, uid, env, mkt))
            R.step_once(db, u.id, M.Env.paper, M.Market.kr)
        finally:
            R.get_broker = saved

        rejected = [o for o in orders() if o.status == M.OrderStatus.rejected]
        pending = [o for o in orders() if o.status == M.OrderStatus.pending]
        check("전송 실패는 rejected 로 남는다", len(rejected) == 1, [o.status for o in orders()])
        check("미체결(pending)로 쌓이지 않는다", not pending, [o.status for o in orders()])
        check("거부 사유가 남는다", "500" in (rejected[0].note or ""), rejected[0].note)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 7. 시각 직렬화
# ---------------------------------------------------------------------------
def check_time_serialization() -> None:
    print("\n[7] 거래 시각 표기")
    with TestClient(app) as c:
        r = c.post("/api/auth/signup",
                   json={"email": "clock@kairo.dev", "name": "점검", "password": "kairo1234"})
        H = {"authorization": f"Bearer {r.json()['access_token']}"}
        c.post("/api/orders", params={"env": "paper", "market": "kr"}, headers=H,
               json={"symbol": "005930", "side": "buy", "quantity": 1, "price": 0,
                     "order_type": "market"})
        rows = c.get("/api/orders", params={"env": "paper", "market": "kr"},
                     headers=H).json()["items"]
        check("주문이 조회된다", len(rows) >= 1, rows)
        created = rows[0]["created_at"]
        check("created_at 이 UTC임을 밝힌다", created.endswith("Z"), created)
        filled = rows[0].get("filled_at")
        check("filled_at 도 마찬가지", filled is None or filled.endswith("Z"), filled)


# ---------------------------------------------------------------------------
# 8. 포트폴리오 집계
# ---------------------------------------------------------------------------
def check_portfolio() -> None:
    print("\n[8] 포트폴리오")
    import app.api.routes_trading as rt

    with TestClient(app) as c:
        r = c.post("/api/auth/signup",
                   json={"email": "pf@kairo.dev", "name": "점검", "password": "kairo1234"})
        H = {"authorization": f"Bearer {r.json()['access_token']}"}
        P = {"env": "paper", "market": "kr"}

        def buy_or_sell(symbol, side, qty):
            return c.post("/api/orders", params=P, headers=H,
                          json={"symbol": symbol, "side": side, "quantity": qty,
                                "price": 0, "order_type": "market"}).json()

        def pf():
            return c.get("/api/portfolio", params=P, headers=H).json()

        d = pf()
        check("빈 계좌는 현금 비중 100%", d["cash_weight_pct"] == 100.0, d["cash_weight_pct"])
        check("보유도 청산도 없다", not d["holdings"] and not d["closed"], d)

        buy_or_sell("005930", "buy", 10)
        buy_or_sell("000660", "buy", 2)
        d = pf()
        check("보유 두 종목", len(d["holdings"]) == 2,
              [h["symbol"] for h in d["holdings"]])
        total = d["cash_weight_pct"] + sum(h["weight_pct"] for h in d["holdings"])
        check("현금 + 종목 비중이 100%", abs(total - 100) < 0.3, total)
        check("보유 종목에 체결 건수가 붙는다",
              all(h["trade_count"] >= 1 for h in d["holdings"]),
              [(h["symbol"], h["trade_count"]) for h in d["holdings"]])
        check("계좌 조회와 평가자산이 같다",
              c.get("/api/account", params=P, headers=H).json()["total_equity"]
              == d["total_equity"])

        sell = buy_or_sell("005930", "sell", 10)
        check("매도 주문에 실현손익이 실린다", "realized_pnl" in sell, sell)
        # 같은 가격에 사고 팔았으므로 실현손익은 정확히 비용(수수료+세금)만큼 손실이다.
        check("실현손익 = -(수수료+세금)",
              round(sell["realized_pnl"]) == -round(sell["fee"]),
              (sell["realized_pnl"], sell["fee"]))

        d = pf()
        check("전량 매도한 종목은 보유에서 빠진다",
              [h["symbol"] for h in d["holdings"]] == ["000660"],
              [h["symbol"] for h in d["holdings"]])
        check("청산 종목으로 넘어간다",
              [x["symbol"] for x in d["closed"]] == ["005930"], d["closed"])
        check("청산 종목의 체결 건수는 매수+매도",
              d["closed"][0]["trade_count"] == 2, d["closed"][0])
        check("실현손익 합계가 맞는다",
              d["realized_total"] == d["closed"][0]["realized_pnl"],
              (d["realized_total"], d["closed"][0]["realized_pnl"]))
        check("시뮬레이터에서는 실현손익을 신뢰할 수 있다", d["realized_supported"] is True)
        check("마지막 거래 시각도 UTC 표기",
              d["closed"][0]["last_traded_at"].endswith("Z"), d["closed"][0]["last_traded_at"])

        # 증권사 계좌가 붙으면 실현손익을 신뢰할 수 없다고 알린다
        saved = rt.is_live_broker
        try:
            rt.is_live_broker = lambda *a, **k: True
            check("실계좌 연결 시 실현손익 미지원 표기",
                  pf()["realized_supported"] is False)
        finally:
            rt.is_live_broker = saved


if __name__ == "__main__":
    check_api()
    check_fills()
    check_migration()
    check_quote_source()
    check_error_mapping()
    check_order_flood()
    check_time_serialization()
    check_portfolio()
    print()
    if FAILS:
        print("실패한 항목:", ", ".join(FAILS))
        sys.exit(1)
    print("모두 통과했습니다.")
