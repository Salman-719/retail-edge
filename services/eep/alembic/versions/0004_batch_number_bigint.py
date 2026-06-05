"""Widen global_tracking_history.batch_number to BIGINT.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-05

The IEP3 coordinator (R8 refactor) keys batches by window_start_ms rounded to
the window boundary — a monotonic, restart-safe identifier — and stores that
value in global_tracking_history.batch_number as correlation metadata.

window_start_ms is epoch milliseconds (~1.78e12), which exceeds the INT4 range
(max 2,147,483,647). The original schema typed batch_number as INT, causing:

    asyncpg.exceptions.DataError: invalid input for query argument $4:
    1780683120000 (value out of int32 range)

on every write_global_position() call. This migration widens the column to
BIGINT to match the value domain. Idempotent and safe — widening INT→BIGINT
preserves all existing values and the (store_id, batch_number) index.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE global_tracking_history "
        "ALTER COLUMN batch_number TYPE BIGINT"
    )


def downgrade() -> None:
    # Downcast is only safe if no stored value exceeds INT4 range. Because
    # batch_number holds epoch-ms, a real downgrade would fail on live data;
    # this is provided for completeness only.
    op.execute(
        "ALTER TABLE global_tracking_history "
        "ALTER COLUMN batch_number TYPE INTEGER"
    )
