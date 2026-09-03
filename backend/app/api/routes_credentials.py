"""증권사 API 키 관리.

app_key / app_secret / 계좌번호는 저장 시 Fernet으로 암호화하고,
조회 시에는 마스킹된 형태만 돌려준다. 평문은 어떤 응답에도 담기지 않는다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.brokers.kis import KISBroker
from app.brokers.kis_overseas import KISOverseasBroker
from app.core.security import decrypt_secret, encrypt_secret, mask
from app.db.session import get_db
from app.models import AuditLog, BrokerCredential, Env, Market, User, utcnow
from app.schemas import CredentialIn, CredentialOut, VerifyOut

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def _to_out(c: BrokerCredential) -> CredentialOut:
    return CredentialOut(
        id=c.id,
        broker=c.broker,
        env=c.env.value,
        market=c.market.value,
        label=c.label,
        app_key_masked=mask(decrypt_secret(c.app_key_enc)),
        account_no_masked=mask(decrypt_secret(c.account_no_enc), head=2, tail=2),
        is_active=c.is_active,
        last_verified_at=c.last_verified_at,
        last_error=c.last_error,
        updated_at=c.updated_at,
    )


@router.get("", response_model=list[CredentialOut])
def list_credentials(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(BrokerCredential).filter_by(user_id=user.id).all()
    return [_to_out(c) for c in rows]


@router.put("", response_model=CredentialOut)
def upsert_credential(
    payload: CredentialIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    env = Env(payload.env)
    mkt = Market(payload.market)
    cred = (
        db.query(BrokerCredential)
        .filter_by(user_id=user.id, broker=payload.broker, env=env, market=mkt)
        .one_or_none()
    )
    if cred is None:
        cred = BrokerCredential(user_id=user.id, broker=payload.broker, env=env, market=mkt)
        db.add(cred)

    시장 = "미국주식" if mkt == Market.us else "국내주식"
    기본환경 = "모의투자" if env == Env.paper else "실계좌"
    cred.label = payload.label or f"{시장} {기본환경} 계좌"
    cred.app_key_enc = encrypt_secret(payload.app_key.strip())
    cred.app_secret_enc = encrypt_secret(payload.app_secret.strip())
    cred.account_no_enc = encrypt_secret(payload.account_no.strip())
    cred.is_active = True
    cred.last_error = None
    cred.updated_at = utcnow()

    db.add(AuditLog(user_id=user.id, event="credential.upsert", detail=f"{payload.broker}/{env.value}/{mkt.value}"))
    db.commit()
    db.refresh(cred)
    return _to_out(cred)


@router.post("/{cred_id}/verify", response_model=VerifyOut)
def verify_credential(
    cred_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    cred = db.query(BrokerCredential).filter_by(id=cred_id, user_id=user.id).one_or_none()
    if cred is None:
        raise HTTPException(404, "등록된 자격증명이 없습니다.")

    cls = KISOverseasBroker if cred.market == Market.us else KISBroker
    broker = cls(
        app_key=decrypt_secret(cred.app_key_enc),
        app_secret=decrypt_secret(cred.app_secret_enc),
        account_no=decrypt_secret(cred.account_no_enc),
        is_paper=(cred.env == Env.paper),
    )
    ok, message = broker.verify()
    cred.last_verified_at = utcnow() if ok else cred.last_verified_at
    cred.last_error = None if ok else message
    db.add(AuditLog(user_id=user.id, event="credential.verify", detail=f"{cred.env.value}/{cred.market.value}:{ok}"))
    db.commit()
    return VerifyOut(ok=ok, message=message)


@router.delete("/{cred_id}", status_code=204)
def delete_credential(
    cred_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    cred = db.query(BrokerCredential).filter_by(id=cred_id, user_id=user.id).one_or_none()
    if cred is None:
        raise HTTPException(404, "등록된 자격증명이 없습니다.")
    db.delete(cred)
    db.add(AuditLog(user_id=user.id, event="credential.delete", detail=f"{cred.env.value}/{cred.market.value}"))
    db.commit()
