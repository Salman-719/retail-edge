"""Add pos_transactions table.

Revision ID: 003
Revises: 002
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pos_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", sa.String(255), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("items_count", sa.Integer()),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("zone_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_pos_transactions_store_id", "pos_transactions", ["store_id"])
    op.create_index("ix_pos_transactions_store_ts", "pos_transactions", ["store_id", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_pos_transactions_store_ts", "pos_transactions")
    op.drop_index("ix_pos_transactions_store_id", "pos_transactions")
    op.drop_table("pos_transactions")
