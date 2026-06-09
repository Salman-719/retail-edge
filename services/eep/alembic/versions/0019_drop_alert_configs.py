"""Remove the retired store-wide alert configuration table.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alert_configs;")


def downgrade() -> None:
    raise NotImplementedError("0019_drop_alert_configs is forward-only.")
