"""Drop the retired alert_configs table (D5).

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-09

The store-wide alert_configs knob set was superseded by per-rule alert_rules (D3).
Its sensible numbers now live in app/core/alert_defaults.py as create-form defaults.
No runtime reader remains (IEP4 is on alert_rules; the EEP settings endpoints +
store-create auto-insert were removed in D5). Forward-only; downgrade re-creates the
table EMPTY (prior per-store rows are not restored — they are no longer used).
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alert_configs;")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_configs (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                 UUID NOT NULL UNIQUE REFERENCES stores(id) ON DELETE CASCADE,
            shift_start_grace_min    INTEGER NOT NULL DEFAULT 15,
            absence_threshold_min    INTEGER NOT NULL DEFAULT 15,
            queue_people_threshold   INTEGER NOT NULL DEFAULT 10,
            queue_wait_min_threshold INTEGER NOT NULL DEFAULT 7,
            queue_alert_cooldown_min INTEGER NOT NULL DEFAULT 15,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
