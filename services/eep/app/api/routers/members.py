"""Store member management endpoints."""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.core.email import send_invitation_email
from app.core.redis_client import get_redis
from app.middleware.store_auth import StoreContext, get_store_context, require_owner, require_owner_or_manager
from app.models.store import Store
from app.models.invitation import Invitation
from app.models.store_member import StoreMember, StoreMemberPermission
from app.models.user import User
from app.core.auth import hash_password
from app.schemas.member import (
    InviteMemberRequest,
    InviteResponse,
    InvitationListItem,
    MemberListItem,
    PatchMemberRequest,
)

router = APIRouter(tags=["members"])


@router.get("/store/{slug}/members", response_model=list[MemberListItem])
async def list_members(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    result = await db.execute(
        select(StoreMember, User)
        .join(User, User.id == StoreMember.user_id)
        .where(StoreMember.store_id == ctx.store_id)
    )
    rows = result.all()

    items = []
    for member, user in rows:
        perm_result = await db.execute(
            select(StoreMemberPermission.permission)
            .where(StoreMemberPermission.store_member_id == member.id, StoreMemberPermission.granted == True)
        )
        perms = [row[0] for row in perm_result.all()]
        items.append(
            MemberListItem(
                id=member.id,
                user_id=user.id,
                name=user.name,
                email=user.email,
                role=member.role,
                permissions=perms,
                last_active_at=user.last_active_at,
                created_at=member.created_at,
            )
        )
    return items


@router.post("/store/{slug}/members/invite", response_model=InviteResponse, status_code=201)
async def invite_member(
    body: InviteMemberRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    if body.role not in ("manager", "viewer"):
        raise HTTPException(status_code=422, detail={"error": "Role must be manager or viewer", "code": "INVALID_ROLE"})

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=3)

    invitation = Invitation(
        store_id=ctx.store_id,
        invited_email=str(body.email),
        role=body.role,
        permissions={k: v for k, v in body.permissions.items()},
        token=token,
        invited_by=ctx.user_id,
        expires_at=expires_at,
    )
    db.add(invitation)
    await db.flush()

    await write_audit_log(
        db, "member_invited", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="invitation", entity_id=invitation.id,
        after_state={"email": str(body.email), "role": body.role},
    )
    await db.commit()

    store_result = await db.execute(select(Store).where(Store.id == ctx.store_id))
    store = store_result.scalar_one()
    await send_invitation_email(str(body.email), store.name, store.slug, token)

    return InviteResponse(invitation_id=invitation.id, expires_at=expires_at, token=token)


@router.get("/store/{slug}/members/invitations", response_model=list[InvitationListItem])
async def list_invitations(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    result = await db.execute(
        select(Invitation)
        .where(Invitation.store_id == ctx.store_id, Invitation.accepted_at == None)
        .order_by(Invitation.created_at.desc())
    )
    invitations = result.scalars().all()
    return [
        InvitationListItem(
            id=inv.id,
            invited_email=inv.invited_email,
            role=inv.role,
            expires_at=inv.expires_at,
            accepted_at=inv.accepted_at,
            created_at=inv.created_at,
        )
        for inv in invitations
    ]


@router.delete("/store/{slug}/members/invitations/{invitation_id}", status_code=204)
async def cancel_invitation(
    invitation_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    result = await db.execute(
        select(Invitation).where(Invitation.id == invitation_id, Invitation.store_id == ctx.store_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail={"error": "Invitation not found", "code": "NOT_FOUND"})

    await db.delete(inv)
    await db.commit()


@router.patch("/store/{slug}/members/{member_id}", response_model=dict)
async def patch_member(
    member_id: uuid.UUID,
    body: PatchMemberRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
):
    require_owner_or_manager(ctx)

    result = await db.execute(
        select(StoreMember).where(StoreMember.id == member_id, StoreMember.store_id == ctx.store_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail={"error": "Member not found", "code": "NOT_FOUND"})

    if body.role is not None:
        member.role = body.role

    if body.permissions is not None:
        await db.execute(delete(StoreMemberPermission).where(StoreMemberPermission.store_member_id == member.id))
        for perm_name, granted in body.permissions.items():
            if granted:
                db.add(StoreMemberPermission(store_member_id=member.id, permission=perm_name, granted=True))

    await write_audit_log(
        db, "member_role_changed", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="store_member", entity_id=member.id,
    )

    # Invalidate Redis perms cache for this member
    await r.delete(f"member_perms:{member.user_id}:{ctx.store_id}")

    await db.commit()
    return {"status": "updated"}


@router.delete("/store/{slug}/members/{member_id}", status_code=204)
async def remove_member(
    member_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
):
    require_owner_or_manager(ctx)

    result = await db.execute(
        select(StoreMember).where(StoreMember.id == member_id, StoreMember.store_id == ctx.store_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail={"error": "Member not found", "code": "NOT_FOUND"})

    await r.delete(f"member_perms:{member.user_id}:{ctx.store_id}")
    removed_user_id = member.user_id
    await db.delete(member)
    await db.flush()

    # Deactivate the user if they have no remaining store memberships
    remaining = await db.execute(
        select(func.count()).select_from(StoreMember).where(StoreMember.user_id == removed_user_id)
    )
    if (remaining.scalar() or 0) == 0:
        await db.execute(
            update(User)
            .where(User.id == removed_user_id)
            .values(is_active=False, deactivated_at=datetime.now(timezone.utc))
        )

    await write_audit_log(
        db, "member_removed", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="store_member", entity_id=member_id,
    )
    await db.commit()


@router.post("/store/{slug}/members/draft-discard-request", status_code=200)
async def draft_discard_request(
    ctx: StoreContext = Depends(get_store_context),
):
    # In production: send email to current draft owner. For now: log only.
    return {"status": "request_sent"}
