from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import AgentConfig, CashAccount, Env, User
from app.schemas import LoginIn, SignupIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _bootstrap(db: Session, user: User) -> None:
    """신규 계정에 두 환경(모의/실계좌)의 기본 설정을 만들어 둔다."""
    for env in (Env.paper, Env.live):
        db.add(CashAccount(user_id=user.id, env=env))
        db.add(AgentConfig(user_id=user.id, env=env, universe="005930,000660,035420"))
    db.commit()


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(payload: SignupIn, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다.")
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _bootstrap(db, user)
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 맞지 않습니다.")
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
