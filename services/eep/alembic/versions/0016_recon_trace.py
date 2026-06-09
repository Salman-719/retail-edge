"""debug.recon_trace — optional IEP3 reconciliation trace.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-09

IEP3 writes these rows only when the Redis-gated debug trace flag is enabled.
The table is intentionally isolated under the debug schema and is not part of
analytics source-of-truth data.
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS debug")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS debug.recon_trace (
            id           BIGSERIAL    PRIMARY KEY,
            store_id     UUID         NOT NULL,
            batch_number BIGINT       NOT NULL,
            event_type   VARCHAR(20)  NOT NULL
                         CHECK (event_type IN ('graph', 'spatial_vote', 'reid_fallback', 'selection')),
            detail       JSONB,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_recon_trace_store_batch
            ON debug.recon_trace(store_id, batch_number);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS debug.recon_trace")
