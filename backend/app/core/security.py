"""비밀번호 해싱, JWT 발급/검증, 브로커 자격증명 대칭키 암호화."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# --------------------------------------------------------------------------
# 비밀번호
# --------------------------------------------------------------------------
# passlib/bcrypt 의존성을 줄이기 위해 PBKDF2-HMAC-SHA256을 직접 사용한다.
_PBKDF2_ROUNDS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_b64, dk_b64 = stored.split("$")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(rounds)
        )
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def create_access_token(subject: str | int, ttl_minutes: int | None = None) -> str:
    ttl = ttl_minutes or settings.access_token_ttl_min
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# --------------------------------------------------------------------------
# 브로커 자격증명 암호화
# --------------------------------------------------------------------------
_fernet = Fernet(settings.master_key.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_secret(cipher: str) -> str:
    try:
        return _fernet.decrypt(cipher.encode()).decode()
    except InvalidToken as exc:  # 마스터 키가 바뀐 경우
        raise ValueError(
            "자격증명을 복호화할 수 없습니다. MASTER_KEY가 변경되었는지 확인하세요."
        ) from exc


def mask(value: str, head: int = 4, tail: int = 4) -> str:
    """앞 4자 / 뒤 4자만 남기고 마스킹. 화면과 로그에는 이 형태만 노출한다."""
    if not value:
        return ""
    if len(value) <= head + tail:
        return "•" * len(value)
    return f"{value[:head]}{'•' * 8}{value[-tail:]}"
