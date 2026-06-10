"""Add constraints and zones.priority column.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-04

All ALTER TABLE statements run under AUTOCOMMIT (set in env.py). Each uses
IF NOT EXISTS / IF EXISTS so the migration is fully idempotent — safe to run
against both fresh DBs (schema.sql applied first) and existing ones.

Note: uq_tracking_history_observation will fail if duplicate
(camera_id, local_id, timestamp_ms) rows already exist in the table.
That scenario should not occur in practice as IEP2 always writes distinct
frames per batch.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD CONSTRAINT IF NOT EXISTS is not valid PostgreSQL syntax in any released version.
    # Use DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL; END; $$ instead —
    # the canonical PostgreSQL idiom for idempotent constraint addition.

    # Unique constraint: prevents double-writing the same frame observation.
    # Check existence first — ADD CONSTRAINT UNIQUE raises duplicate_table (42P07)
    # if the backing index already exists, not duplicate_object (42710), so a
    # plain EXCEPTION WHEN duplicate_object doesn't catch it.
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF NOT EXISTS ("
        "  SELECT 1 FROM information_schema.table_constraints "
        "  WHERE table_name='tracking_history' "
        "  AND constraint_name='uq_tracking_history_observation'"
        ") THEN "
        "ALTER TABLE tracking_history "
        "ADD CONSTRAINT uq_tracking_history_observation "
        "UNIQUE (camera_id, local_id, timestamp_ms); "
        "END IF; "
        "END; $$"
    ))

    # centroid BYTEA check — superseded by migration 0005 (column renamed to
    # `embeddings` in migration 0013). Only apply when the legacy `centroid`
    # column still exists (upgrade path from pre-0013 DBs); skip on fresh DBs
    # where schema.sql already uses the `embeddings` column layout.
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "  WHERE table_name='local_centroids' AND column_name='centroid'"
        ") THEN "
        "ALTER TABLE local_centroids "
        "ADD CONSTRAINT chk_centroid_size "
        "CHECK (octet_length(centroid) = 2048); "
        "END IF; "
        "END; $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "  WHERE table_name='global_embeddings' AND column_name='centroid'"
        ") THEN "
        "ALTER TABLE global_embeddings "
        "ADD CONSTRAINT chk_embedding_size "
        "CHECK (octet_length(centroid) = 2048); "
        "END IF; "
        "END; $$"
    ))

    # Enforce schedule time ordering at DB level (also validated in Pydantic schema).
    # camera_schedules was removed from schema.sql in a later refactor; guard
    # so fresh DBs (where the table never existed) skip this silently.
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "  SELECT 1 FROM information_schema.tables "
        "  WHERE table_name='camera_schedules'"
        ") AND NOT EXISTS ("
        "  SELECT 1 FROM information_schema.table_constraints "
        "  WHERE table_name='camera_schedules' "
        "  AND constraint_name='chk_schedule_time'"
        ") THEN "
        "ALTER TABLE camera_schedules "
        "ADD CONSTRAINT chk_schedule_time "
        "CHECK (start_time < end_time); "
        "END IF; "
        "END; $$"
    ))

    # Zone display priority — 0 = default render order.
    op.execute(sa.text(
        "ALTER TABLE zones "
        "ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE zones DROP COLUMN IF EXISTS priority"
    ))
    op.execute(sa.text(
        "ALTER TABLE camera_schedules DROP CONSTRAINT IF EXISTS chk_schedule_time"
    ))
    op.execute(sa.text(
        "ALTER TABLE global_embeddings DROP CONSTRAINT IF EXISTS chk_embedding_size"
    ))
    op.execute(sa.text(
        "ALTER TABLE local_centroids DROP CONSTRAINT IF EXISTS chk_centroid_size"
    ))
    op.execute(sa.text(
        "ALTER TABLE tracking_history DROP CONSTRAINT IF EXISTS uq_tracking_history_observation"
    ))
