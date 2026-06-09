"""Embedding store — replace single EMA centroids with packed embedding heaps.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-09

IEP2 now persists up to 10 top-quality raw ReID embeddings per local track.
IEP3 merges those heaps into per-camera global identity galleries. Existing
single-centroid rows cannot be converted losslessly, so both appearance tables
are cleared before the layout changes.
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_CENTROID_BYTES = 8192  # 2048 float32 values, used by downgrade only.


def upgrade() -> None:
    op.execute("DELETE FROM local_centroids")
    op.execute(
        "ALTER TABLE local_centroids DROP CONSTRAINT IF EXISTS chk_centroid_size"
    )
    op.execute("ALTER TABLE local_centroids DROP COLUMN IF EXISTS centroid")
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE local_centroids ADD COLUMN embeddings BYTEA NOT NULL; "
        "EXCEPTION WHEN duplicate_column THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE local_centroids "
        "ADD COLUMN embedding_count SMALLINT NOT NULL DEFAULT 0; "
        "EXCEPTION WHEN duplicate_column THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE local_centroids "
        "ADD COLUMN quality_scores BYTEA NOT NULL DEFAULT ''::bytea; "
        "EXCEPTION WHEN duplicate_column THEN NULL; END $$"
    )

    op.execute("DELETE FROM global_embeddings")
    op.execute(
        "ALTER TABLE global_embeddings DROP CONSTRAINT IF EXISTS chk_embedding_size"
    )
    op.execute("ALTER TABLE global_embeddings DROP COLUMN IF EXISTS centroid")
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE global_embeddings ADD COLUMN embeddings BYTEA NOT NULL; "
        "EXCEPTION WHEN duplicate_column THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE global_embeddings "
        "ADD COLUMN embedding_count SMALLINT NOT NULL DEFAULT 0; "
        "EXCEPTION WHEN duplicate_column THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE global_embeddings "
        "ADD COLUMN quality_scores BYTEA NOT NULL DEFAULT ''::bytea; "
        "EXCEPTION WHEN duplicate_column THEN NULL; END $$"
    )


def downgrade() -> None:
    op.execute("DELETE FROM local_centroids")
    op.execute("ALTER TABLE local_centroids DROP COLUMN IF EXISTS embeddings")
    op.execute("ALTER TABLE local_centroids DROP COLUMN IF EXISTS embedding_count")
    op.execute("ALTER TABLE local_centroids DROP COLUMN IF EXISTS quality_scores")
    op.execute("ALTER TABLE local_centroids ADD COLUMN centroid BYTEA NOT NULL")
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE local_centroids "
        f"ADD CONSTRAINT chk_centroid_size CHECK (octet_length(centroid) = {_CENTROID_BYTES}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )

    op.execute("DELETE FROM global_embeddings")
    op.execute("ALTER TABLE global_embeddings DROP COLUMN IF EXISTS embeddings")
    op.execute("ALTER TABLE global_embeddings DROP COLUMN IF EXISTS embedding_count")
    op.execute("ALTER TABLE global_embeddings DROP COLUMN IF EXISTS quality_scores")
    op.execute("ALTER TABLE global_embeddings ADD COLUMN centroid BYTEA NOT NULL")
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE global_embeddings "
        f"ADD CONSTRAINT chk_embedding_size CHECK (octet_length(centroid) = {_CENTROID_BYTES}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
