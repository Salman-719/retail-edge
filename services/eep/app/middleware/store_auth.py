"""
5-step store-scoped auth middleware implemented as a FastAPI dependency.

Step 1 — JWT extraction and validation
Step 2 — slug → store_id resolution (Redis cache → DB fallback)
Step 3 — user membership check (owner via stores.created_by OR store_members)
Step 4 — role + permissions load (Redis cache → DB fallback, 5 min TTL)
Step 5 — returns StoreContext; endpoint-level role/permission checks use helpers below
"""
import json
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decode_access_token
from app.core.database import get_db
from app.core.redis_client import get_redis
from app.models.store import Store
from app.models.store_member import StoreMember, StoreMemberPermission

bearer_scheme = HTTPBearer(auto_error=False)

SLUG_CACHE_TTL = 3600  # 1 hour
PERMS_CACHE_TTL = 300  # 5 minutes


@dataclass
class StoreContext:
    user_id: uuid.UUID
    account_type: str
    store_id: uuid.UUID
    store: Store
    is_owner: bool
    role: str | None  # None if owner and not in store_members
    permissions: set[str] = field(default_factory=set)


async def _resolve_slug(slug: str, r: redis.Redis, db: AsyncSession) -> uuid.UUID:
    cache_key = f"store_slug:{slug}"
    cached = await r.get(cache_key)
    if cached:
        return uuid.UUID(cached.decode())

    result = await db.execute(select(Store).where(Store.slug == slug))
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail={"error": "Store not found", "code": "STORE_NOT_FOUND"})

    await r.setex(cache_key, SLUG_CACHE_TTL, str(store.id))
    return store.id


async def _load_perms(
    user_id: uuid.UUID,
    store_id: uuid.UUID,
    is_owner: bool,
    member: StoreMember | None,
    r: redis.Redis,
    db: AsyncSession,
) -> tuple[str | None, set[str]]:
    if is_owner and member is None:
        return None, set()  # owners have full access; no need to cache

    cache_key = f"member_perms:{user_id}:{store_id}"
    cached = await r.get(cache_key)
    if cached:
        data = json.loads(cached)
        return data["role"], set(data["permissions"])

    role = member.role if member else None
    perm_result = await db.execute(
        select(StoreMemberPermission.permission)
        .where(StoreMemberPermission.store_member_id == member.id, StoreMemberPermission.granted == True)
    )
    permissions = {row[0] for row in perm_result.all()}

    await r.setex(cache_key, PERMS_CACHE_TTL, json.dumps({"role": role, "permissions": list(permissions)}))
    return role, permissions


async def get_store_context(
    slug: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
) -> StoreContext:
    # Step 1: JWT
    if not credentials:
        raise HTTPException(status_code=401, detail={"error": "Authorization required", "code": "NO_AUTH"})
    payload = decode_access_token(credentials.credentials)
    user_id = uuid.UUID(payload["sub"])
    account_type = payload["account_type"]

    # Step 2: slug → store_id (with Redis cache)
    store_id = await _resolve_slug(slug, r, db)
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail={"error": "Store not found", "code": "STORE_NOT_FOUND"})

    # Step 3: membership check
    is_owner = (store.created_by == user_id)
    member: StoreMember | None = None
    if not is_owner:
        mem_result = await db.execute(
            select(StoreMember).where(
                StoreMember.user_id == user_id,
                StoreMember.store_id == store_id,
            )
        )
        member = mem_result.scalar_one_or_none()
        if member is None:
            raise HTTPException(status_code=403, detail={"error": "Not a member of this store", "code": "NOT_MEMBER"})
    else:
        # Owner may also appear in store_members; load if present (for role)
        mem_result = await db.execute(
            select(StoreMember).where(
                StoreMember.user_id == user_id,
                StoreMember.store_id == store_id,
            )
        )
        member = mem_result.scalar_one_or_none()

    # Step 4: role + permissions (Redis cache)
    role, permissions = await _load_perms(user_id, store_id, is_owner, member, r, db)

    return StoreContext(
        user_id=user_id,
        account_type=account_type,
        store_id=store_id,
        store=store,
        is_owner=is_owner,
        role=role,
        permissions=permissions,
    )


def require_owner(ctx: StoreContext) -> None:
    if not ctx.is_owner:
        raise HTTPException(status_code=403, detail={"error": "Owner access required", "code": "OWNER_REQUIRED"})


def require_owner_or_manager(ctx: StoreContext) -> None:
    if not ctx.is_owner and ctx.role != "manager":
        raise HTTPException(
            status_code=403,
            detail={"error": "Owner or manager access required", "code": "MANAGER_REQUIRED"},
        )


def require_permission(ctx: StoreContext, permission: str) -> None:
    if ctx.is_owner:
        return
    if permission not in ctx.permissions:
        raise HTTPException(
            status_code=403,
            detail={"error": f"Missing permission: {permission}", "code": "PERMISSION_DENIED"},
        )
