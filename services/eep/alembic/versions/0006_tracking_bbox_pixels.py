"""Add bbox pixel columns to tracking_history (dev projection debugging).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-07

Persists each detection's bbox in full-resolution pixels (x1, y1, x2, y2) — the
same unscaled bbox IEP2 feeds to the floor projector. This lets the dev tools
show the bbox and its bottom-centre foot point alongside the projected
floor_x/floor_y for comparison. Idempotent and nullable (older rows stay NULL).
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tracking_history
            ADD COLUMN IF NOT EXISTS bbox_x1 INTEGER,
            ADD COLUMN IF NOT EXISTS bbox_y1 INTEGER,
            ADD COLUMN IF NOT EXISTS bbox_x2 INTEGER,
            ADD COLUMN IF NOT EXISTS bbox_y2 INTEGER
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tracking_history
            DROP COLUMN IF EXISTS bbox_x1,
            DROP COLUMN IF EXISTS bbox_y1,
            DROP COLUMN IF EXISTS bbox_x2,
            DROP COLUMN IF EXISTS bbox_y2
        """
    )
