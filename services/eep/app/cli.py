"""Management CLI for EEP — out-of-band admin provisioning (A3).

There is no public "make me admin" endpoint, by design. Super-admins are minted by
whoever controls the deployment:

    python -m app.cli create-admin --email ops@example.com --password '...' --name Ops

Idempotent: re-running promotes an existing user or no-ops; it never errors and never
resets a password unless ``--force`` is given. Passwords are bcrypt-hashed via passlib.

``create_or_promote_admin`` is shared with the optional env-bootstrap in
``app.main`` lifespan, so both paths use exactly the same logic.
"""
import argparse
import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.core.database import AsyncSessionLocal
from app.models.user import User

logger = logging.getLogger(__name__)


async def create_or_promote_admin(
    db: AsyncSession,
    email: str,
    password: str | None,
    name: str | None = None,
    force: bool = False,
) -> tuple[User, str]:
    """Upsert a super-admin by email. The caller is responsible for committing.

    Returns ``(user, action)`` where action is one of
    ``'created' | 'promoted' | 'updated' | 'noop'``.

    Idempotent: an existing super-admin is a no-op. An existing non-admin user is
    promoted (``is_super_admin = True``). The password is only (re)set when creating
    a new user, or on an existing user when ``force`` is set — re-running without
    ``--force`` never resets a password.
    """
    email = email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        if not password:
            raise ValueError("a password is required to create a new admin")
        user = User(
            account_type="owner",  # admins are owner-shaped; elevation is is_super_admin
            email=email,
            password_hash=hash_password(password),
            name=(name or email.split("@", 1)[0]),
            is_super_admin=True,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        return user, "created"

    action = "noop"
    if not user.is_super_admin:
        user.is_super_admin = True
        action = "promoted"
    if force and password:
        user.password_hash = hash_password(password)
        action = action if action != "noop" else "updated"
    if name and user.name != name:
        user.name = name
        action = action if action != "noop" else "updated"
    await db.flush()
    return user, action


async def _run_create_admin(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        try:
            user, action = await create_or_promote_admin(
                db,
                email=args.email,
                password=args.password,
                name=args.name,
                force=args.force,
            )
            await db.commit()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(
        f"{action}: {user.email} "
        f"(user_id={user.id}, is_super_admin={user.is_super_admin})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="EEP management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "create-admin", help="Create or promote a super-admin (idempotent)"
    )
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--name", default=None)
    p.add_argument(
        "--force",
        action="store_true",
        help="Update the password of an existing user (ignored on re-run otherwise)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create-admin":
        return asyncio.run(_run_create_admin(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
