"""Add severity to alert_rules and alerts (D3).

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-09

Operators pick a severity per alert rule; IEP4 copies the firing rule's severity
onto the alert row so history retains it. Camera-health producers (CAT F) set
their own. VARCHAR(10) CHECK (low/medium/high/critical), default 'medium'.

alert_rules lives only in migrations (0011), not schema.sql; alerts is in both.
Idempotent ADD COLUMN IF NOT EXISTS so it is a no-op where schema.sql already has it.
Forward-only.
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_SEVERITY_DDL = (
    "ADD COLUMN IF NOT EXISTS severity VARCHAR(10) NOT NULL DEFAULT 'medium' "
    "CHECK (severity IN ('low', 'medium', 'high', 'critical'))"
)


def upgrade() -> None:
    op.execute(f"ALTER TABLE alert_rules {_SEVERITY_DDL};")
    op.execute(f"ALTER TABLE alerts {_SEVERITY_DDL};")


def downgrade() -> None:
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS severity;")
    op.execute("ALTER TABLE alert_rules DROP COLUMN IF EXISTS severity;")
