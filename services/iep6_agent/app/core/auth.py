"""JWT and store-membership authorization for IEP6 HTTP endpoints."""
import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization required")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        payload["sub"] = str(uuid.UUID(payload["sub"]))
        return payload
    except (JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def authorize_store_slug(
    slug: str,
    payload: dict,
    session: AsyncSession,
) -> str:
    row = (
        await session.execute(
            text(
                """
                SELECT s.id
                FROM stores s
                WHERE s.slug = :slug
                  AND (
                    :is_system
                    OR s.created_by = CAST(:user_id AS uuid)
                    OR EXISTS (
                        SELECT 1
                        FROM store_members sm
                        WHERE sm.store_id = s.id
                          AND sm.user_id = CAST(:user_id AS uuid)
                    )
                  )
                """
            ),
            {
                "slug": slug,
                "user_id": payload["sub"],
                "is_system": payload.get("account_type") == "system",
            },
        )
    ).first()
    if row:
        return str(row[0])

    store_exists = (
        await session.execute(
            text("SELECT 1 FROM stores WHERE slug = :slug"),
            {"slug": slug},
        )
    ).first()
    if not store_exists:
        raise HTTPException(status_code=404, detail=f"store '{slug}' not found")
    raise HTTPException(status_code=403, detail="Not authorized for this store")


async def authorize_store_id(
    store_id: str,
    payload: dict,
    session: AsyncSession,
) -> str:
    try:
        normalized_store_id = str(uuid.UUID(store_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid store_id")

    row = (
        await session.execute(
            text(
                """
                SELECT 1
                FROM stores s
                WHERE s.id = CAST(:store_id AS uuid)
                  AND (
                    :is_system
                    OR s.created_by = CAST(:user_id AS uuid)
                    OR EXISTS (
                        SELECT 1
                        FROM store_members sm
                        WHERE sm.store_id = s.id
                          AND sm.user_id = CAST(:user_id AS uuid)
                    )
                  )
                """
            ),
            {
                "store_id": normalized_store_id,
                "user_id": payload["sub"],
                "is_system": payload.get("account_type") == "system",
            },
        )
    ).first()
    if not row:
        raise HTTPException(status_code=403, detail="Not authorized for this store")
    return normalized_store_id
