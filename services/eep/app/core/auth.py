import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    user_id: uuid.UUID, account_type: str, is_super_admin: bool = False
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "account_type": account_type,
        "is_super_admin": is_super_admin,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash)."""
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, token_hash


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail={"error": "Invalid or expired token", "code": "TOKEN_INVALID"})


async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail={"error": "Authorization header missing", "code": "NO_AUTH"})
    return decode_access_token(credentials.credentials)


async def require_super_admin(payload: dict = Depends(get_current_user_payload)) -> dict:
    """Gate for non-store-scoped admin/dev routes (A4).

    Allows super-admins, or any authenticated user when DEBUG_MODE is on (local-dev
    convenience). NOT a store-membership gate — use get_store_context for those.
    """
    if payload.get("is_super_admin"):
        return payload
    if settings.DEBUG_MODE:
        return payload
    raise HTTPException(
        status_code=403, detail={"error": "Super-admin required", "code": "ADMIN_REQUIRED"}
    )
