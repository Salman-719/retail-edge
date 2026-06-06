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
    op.execute(sa.text(
        "DO $$ BEGIN "
        "ALTER TABLE tracking_history "
        "ADD CONSTRAINT uq_tracking_history_observation "
        "UNIQUE (camera_id, local_id, timestamp_ms); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END; $$"
    ))

    # centroid BYTEA must hold exactly 512 float32 values = 512 * 4 = 2048 bytes.
    # NOTE: superseded by migration 0005 (resnet50_msmt17 → 2048-dim = 8192 bytes).
    op.execute(sa.text(
        "DO $$ BEGIN "
        "ALTER TABLE local_centroids "
        "ADD CONSTRAINT chk_centroid_size "
        "CHECK (octet_length(centroid) = 2048); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END; $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "ALTER TABLE global_embeddings "
        "ADD CONSTRAINT chk_embedding_size "
        "CHECK (octet_length(centroid) = 2048); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END; $$"
    ))

    # Enforce schedule time ordering at DB level (also validated in Pydantic schema).
    op.execute(sa.text(
        "DO $$ BEGIN "
        "ALTER TABLE camera_schedules "
        "ADD CONSTRAINT chk_schedule_time "
        "CHECK (start_time < end_time); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END; $$"
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
