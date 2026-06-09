import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_actions import AUDIT_ACTIONS
from app.models.audit_log import AuditLog


async def write_audit_log(
    db: AsyncSession,
    action: str,
    store_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
) -> None:
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")
    log = AuditLog(
        store_id=store_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
    )
    db.add(log)
    await db.flush()
