from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.brokers.base import BrokerError

from app.agent.runner import agent_loop
from app.api import (
    routes_auth,
    routes_connection,
    routes_credentials,
    routes_insight,
    routes_trading,
)
from app.core.config import settings
from app.db.migrate import ensure_columns, ensure_market_axis
from app.db.session import Base, SessionLocal, engine
from app.services.fills import fill_poller
from app.services.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("kairo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401  테이블 등록

    # 기존 DB에 market(kr|us) 축이 없으면 옮긴다. 이미 최신이면 아무 일도 하지 않는다.
    ensure_market_axis(engine, Base)
    Base.metadata.create_all(bind=engine)
    # 테이블을 만든 뒤에 본다. 새로 만들어진 테이블에는 이미 컬럼이 들어 있다.
    ensure_columns(engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    agent_loop.start()
    fill_poller.start()
    log.info("데모 계정: %s / %s", DEMO_EMAIL, DEMO_PASSWORD)
    if not settings.allow_live_trading:
        log.info("실계좌 주문은 잠겨 있습니다 (ALLOW_LIVE_TRADING=false).")
    yield
    agent_loop.stop()
    fill_poller.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="강화학습 기반 자동매매 시스템의 백엔드. 증권사 어댑터를 통해 KIS Open API와 연결된다.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --------------------------------------------------------------------------
# 증권사 쪽 문제는 502로 내보낸다.
#
# 우리 서버의 버그가 아니라 KIS가 응답을 못 준 것이므로, 500과 스택트레이스가 아니라
# 짧은 사유 한 줄이 나가야 한다. 화면도 "증권사가 지금 응답을 안 한다"를 그대로
# 보여 줄 수 있고, 로그도 요청 하나에 60줄씩 쌓이지 않는다.
# 우리 코드의 진짜 버그(TypeError 등)는 여기 걸리지 않고 원래대로 500이 된다.
# --------------------------------------------------------------------------
@app.exception_handler(BrokerError)
async def broker_error_handler(request: Request, exc: BrokerError):
    log.warning("증권사 오류 %s — %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def broker_transport_error_handler(request: Request, exc: httpx.HTTPError):
    log.warning("증권사 통신 실패 %s — %s", request.url.path, exc)
    return JSONResponse(
        status_code=502,
        content={"detail": "증권사 서버에서 응답을 받지 못했습니다. 잠시 후 다시 시도하세요."},
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "version": settings.version, "agent_loop": True}


app.include_router(routes_auth.router)
app.include_router(routes_credentials.router)
app.include_router(routes_trading.router)
app.include_router(routes_insight.router)
app.include_router(routes_connection.router)
