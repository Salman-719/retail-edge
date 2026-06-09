"""Auth endpoints — registration, login, token refresh, logout, invite acceptance."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import limiter, RATE_LIMIT_AUTH, RATE_LIMIT_PWRESET
from app.core.audit import write_audit_log
from app.core.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.core.database import get_db
from app.core.config import settings
from app.core.email import send_password_reset_email
from app.models.invitation import Invitation
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.store import Store
from app.models.store_member import StoreMember, StoreMemberPermission
from app.models.user import User
from app.schemas.auth import (
    AcceptInviteRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    StoreRef,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _create_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = create_access_token(user.id, user.account_type, user.is_super_admin)
    raw_refresh, token_hash = create_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    await db.flush()
    return access_token, raw_refresh


async def _build_login_response(db: AsyncSession, user: User) -> LoginResponse:
    access_token, raw_refresh = await _create_tokens(db, user)

    if user.is_super_admin:
        # Super-admin lands on the all-stores fleet dashboard, not a single store.
        result = await db.execute(select(Store).order_by(Store.name))
        stores = [
            StoreRef(id=s.id, name=s.name, slug=s.slug, status=s.status)
            for s in result.scalars().all()
        ]
        return LoginResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            account_type=user.account_type,
            stores=stores,
            redirect_slug=None,
            is_super_admin=True,
        )

    if user.account_type == "owner":
        result = await db.execute(select(Store).where(Store.created_by == user.id))
        stores = [
            StoreRef(id=s.id, name=s.name, slug=s.slug, status=s.status)
            for s in result.scalars().all()
        ]
        return LoginResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            account_type=user.account_type,
            stores=stores,
        )
    else:
        # Sub-account: exactly one store via store_members
        result = await db.execute(
            select(Store)
            .join(StoreMember, StoreMember.store_id == Store.id)
            .where(StoreMember.user_id == user.id)
        )
        store = result.scalar_one_or_none()
        stores = [StoreRef(id=store.id, name=store.name, slug=store.slug, status=store.status)] if store else []
        return LoginResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            account_type=user.account_type,
            stores=stores,
            redirect_slug=store.slug if store else None,
        )


@router.post("/register", response_model=RegisterResponse, status_code=201)
@limiter.limit(RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"error": "Email already registered", "code": "EMAIL_TAKEN"})

    user = User(
        account_type="owner",
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        account_type=user.account_type,
        is_super_admin=user.is_super_admin,
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401, detail={"error": "Invalid credentials", "code": "INVALID_CREDENTIALS"}
        )

    response = await _build_login_response(db, user)

    # Update last_active_at
    await db.execute(
        update(User).where(User.id == user.id).values(last_active_at=datetime.now(timezone.utc))
    )
    await write_audit_log(db, "login", user_id=user.id)
    await db.commit()
    return response


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def refresh_token(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_refresh_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at == None,
        )
    )
    rt = result.scalar_one_or_none()
    if not rt or rt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=401, detail={"error": "Invalid or expired refresh token", "code": "REFRESH_INVALID"}
        )

    user_result = await db.execute(select(User).where(User.id == rt.user_id))
    user = user_result.scalar_one()

    # Rotate: revoke old, issue new
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == rt.id)
        .values(revoked_at=datetime.now(timezone.utc))
    )

    new_access = create_access_token(user.id, user.account_type, user.is_super_admin)
    raw_refresh, new_hash = create_refresh_token()
    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(new_rt)
    await db.commit()
    return RefreshResponse(access_token=new_access, refresh_token=raw_refresh)


@router.post("/logout", status_code=204)
async def logout(body: LogoutRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_refresh_token(body.refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    rt = result.scalar_one_or_none()
    if rt:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.id == rt.id)
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await write_audit_log(db, "logout", user_id=rt.user_id)
        await db.commit()


@router.post("/forgot-password", status_code=200)
@limiter.limit(RATE_LIMIT_PWRESET)
async def forgot_password(request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    # Always return 200 — never reveal whether the email exists
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if user:
        # Invalidate any existing unused tokens for this user
        await db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at == None,
            )
            .values(used_at=datetime.now(timezone.utc))
        )
        raw_token = secrets.token_urlsafe(48)
        prt = PasswordResetToken(
            user_id=user.id,
            token_hash=PasswordResetToken.hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(prt)
        await db.commit()
        await send_password_reset_email(user.email, raw_token)
    return {"message": "If that email exists, a reset link has been sent"}


@router.post("/reset-password", status_code=200)
@limiter.limit(RATE_LIMIT_PWRESET)
async def reset_password(request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    token_hash = PasswordResetToken.hash_token(body.token)
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at == None,
        )
    )
    prt = result.scalar_one_or_none()
    if not prt or prt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail={"error": "This reset link is invalid or has expired.", "code": "RESET_TOKEN_INVALID"},
        )

    await db.execute(
        update(User)
        .where(User.id == prt.user_id)
        .values(password_hash=hash_password(body.new_password))
    )
    prt.used_at = datetime.now(timezone.utc)

    # Revoke all existing refresh tokens so old sessions are invalidated
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == prt.user_id, RefreshToken.revoked_at == None)
        .values(revoked_at=datetime.now(timezone.utc))
    )

    await write_audit_log(db, "password_reset", user_id=prt.user_id)
    await db.commit()
    return {"message": "Password updated successfully"}


# ── Store-scoped auth endpoints ──────────────────────────────────────────────

store_auth_router = APIRouter(tags=["auth"])


@store_auth_router.post("/store/{slug}/auth/login", response_model=LoginResponse)
async def store_login(slug: str, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Tenant-scoped login. Same logic as /auth/login, returns redirect_slug."""
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401, detail={"error": "Invalid credentials", "code": "INVALID_CREDENTIALS"}
        )

    # Verify user has access to this slug
    store_result = await db.execute(select(Store).where(Store.slug == slug))
    store = store_result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail={"error": "Store not found", "code": "STORE_NOT_FOUND"})

    response = await _build_login_response(db, user)
    await db.execute(
        update(User).where(User.id == user.id).values(last_active_at=datetime.now(timezone.utc))
    )
    await write_audit_log(db, "login", store_id=store.id, user_id=user.id)
    await db.commit()
    return response


@store_auth_router.post("/store/{slug}/accept-invite", status_code=201)
async def accept_invite(slug: str, body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    # Look up invitation
    inv_result = await db.execute(
        select(Invitation).where(Invitation.token == body.token)
    )
    invitation = inv_result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail={"error": "Invalid invitation token", "code": "INVITE_NOT_FOUND"})
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=409, detail={"error": "Invitation already accepted", "code": "INVITE_USED"})
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail={"error": "Invitation expired", "code": "INVITE_EXPIRED"})

    store_result = await db.execute(select(Store).where(Store.slug == slug))
    store = store_result.scalar_one_or_none()
    if not store or store.id != invitation.store_id:
        raise HTTPException(status_code=404, detail={"error": "Store not found", "code": "STORE_NOT_FOUND"})

    # Check if user already exists (re-invite edge case)
    user_result = await db.execute(select(User).where(User.email == invitation.invited_email))
    user = user_result.scalar_one_or_none()
    if not user:
        user = User(
            account_type="sub_account",
            email=invitation.invited_email,
            password_hash=hash_password(body.password),
            name=body.name,
            created_by=invitation.invited_by,
        )
        db.add(user)
        await db.flush()
    elif not user.is_active:
        # Previously deactivated — reset their account with the new credentials
        user.name = body.name
        user.password_hash = hash_password(body.password)
        user.is_active = True
        user.deactivated_at = None
        await db.flush()
    else:
        # Active user accepting another store invite — verify their password
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=401,
                detail={"error": "Incorrect password for existing account", "code": "INVALID_PASSWORD"},
            )

    # Create store_member
    member = StoreMember(
        user_id=user.id,
        store_id=store.id,
        role=invitation.role,
        invited_by=invitation.invited_by,
    )
    db.add(member)
    await db.flush()

    # Permissions
    for perm_name, granted in invitation.permissions.items():
        if granted:
            db.add(StoreMemberPermission(store_member_id=member.id, permission=perm_name, granted=True))

    # Mark invitation accepted
    invitation.accepted_at = datetime.now(timezone.utc)
    await write_audit_log(
        db, "member_invited", store_id=store.id, user_id=invitation.invited_by,
        entity_type="store_member", entity_id=member.id,
    )

    access_token = create_access_token(user.id, user.account_type, user.is_super_admin)
    raw_refresh, token_hash = create_refresh_token()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    await db.commit()

    return {"access_token": access_token, "refresh_token": raw_refresh}
