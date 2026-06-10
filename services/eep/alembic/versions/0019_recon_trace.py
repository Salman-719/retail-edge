"""debug.recon_trace — IEP3 reconciliation trace (dev-only, capped). VD1.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-09

A capped, dev-only table in its OWN `debug` schema (never pollutes prod analytics).
IEP3 writes per-batch trace rows ONLY when Redis-gated on; the writer prunes to the
last N batches per store (see repository.write_recon_trace). No FK on store_id —
this is ephemeral diagnostic data, deliberately decoupled. Forward-only.
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS debug;")
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
    op.execute("DROP TABLE IF EXISTS debug.recon_trace;")
