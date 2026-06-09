"""Replace the stale audit action CHECK with application validation.

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE audit_logs "
        "DROP CONSTRAINT IF EXISTS audit_logs_action_check;"
    )


def downgrade() -> None:
    raise NotImplementedError("0017_drop_audit_action_check is forward-only.")
