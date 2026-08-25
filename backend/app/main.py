from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent.runner import agent_loop
from app.api import routes_auth, routes_credentials, routes_insight, routes_trading
from app.core.config import settings
from app.db.migrate import ensure_market_axis
from app.db.session import Base, SessionLocal, engine
from app.services.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("kairo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401  테이블 등록

    # 기존 DB에 market(kr|us) 축이 없으면 옮긴다. 이미 최신이면 아무 일도 하지 않는다.
    ensure_market_axis(engine, Base)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    agent_loop.start()
    log.info("데모 계정: %s / %s", DEMO_EMAIL, DEMO_PASSWORD)
    yield
    agent_loop.stop()


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


@app.get("/api/health")
def health():
    return {"status": "ok", "version": settings.version, "agent_loop": True}


app.include_router(routes_auth.router)
app.include_router(routes_credentials.router)
app.include_router(routes_trading.router)
app.include_router(routes_insight.router)
