"""Add live identity classification and alert severity.

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE global_identities
            ADD COLUMN IF NOT EXISTS is_employee BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS employee_id UUID
                REFERENCES employees(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS idx_global_identities_employee
            ON global_identities(employee_id)
            WHERE employee_id IS NOT NULL;

        ALTER TABLE alert_rules
            ADD COLUMN IF NOT EXISTS severity VARCHAR(10) NOT NULL DEFAULT 'medium'
            CHECK (severity IN ('low', 'medium', 'high', 'critical'));

        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS severity VARCHAR(10) NOT NULL DEFAULT 'medium'
            CHECK (severity IN ('low', 'medium', 'high', 'critical'));
        """
    )


def downgrade() -> None:
    raise NotImplementedError("0018_live_identity_and_alert_severity is forward-only.")
