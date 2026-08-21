from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Env, User


def current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.")
    payload = decode_access_token(authorization.split(" ", 1)[1])
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "세션이 만료되었습니다. 다시 로그인하세요.")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "계정을 찾을 수 없습니다.")
    return user


def env_param(env: str = Query(default="paper", pattern="^(paper|live)$")) -> Env:
    return Env(env)
