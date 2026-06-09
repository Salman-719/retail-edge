"""Embedding store — replace single EMA centroid with a fixed-capacity store of
up to 10 raw embeddings plus per-embedding quality scores.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-08

Background
----------
local_centroids and global_embeddings each stored a single L2-normalised EMA
centroid in a `centroid BYTEA` column (2048 float32 = 8192 bytes after the
resnet50_msmt17 widening in migration 0005). The new ReID design keeps up to 10
*raw* embeddings per row plus a quality score per embedding, so a representative
centroid is recomputed on demand instead of being smeared by an EMA update.

Schema change (identical on both tables)
----------------------------------------
  - DROP  centroid BYTEA              (+ its octet_length CHECK constraint)
  - ADD   embeddings      BYTEA    NOT NULL              -- concat of N * 8192 raw bytes
  - ADD   embedding_count SMALLINT NOT NULL DEFAULT 0    -- 0..10, drives unpack
  - ADD   quality_scores  BYTEA    NOT NULL DEFAULT ''   -- N * 4 raw float32

One embedding = 2048 * 4 = 8192 bytes; max 10 = 81920 bytes. quality_scores is
N float32 = N * 4 bytes.

Existing rows hold the single-centroid layout, which cannot be coerced into the
new packed format, so both tables are emptied first (DELETE). IEP2 repopulates
local_centroids on its next batch; IEP3 repopulates global_embeddings after.
Emptying first also lets `embeddings BYTEA NOT NULL` be added without a default.

Idempotent: each ADD COLUMN uses the project's
`DO $$ ... EXCEPTION WHEN duplicate_column THEN NULL; END $$` idiom (per the
spec's hard constraint — no ADD COLUMN IF NOT EXISTS); drops use IF EXISTS.
Safe on fresh DBs (schema.sql) and on already-migrated ones.

Deviations from source spec (0004_embedding_store_spec.md) — reported separately:
  * revision is 0013 / down_revision 0012, NOT 0004 / 0003. Revisions 0004
    (batch_number BIGINT) and 0005 (resnet50 8192-byte widening) already exist;
    the chain head is 0012. The spec predates 0004..0012.
  * file lives in services/eep/alembic/versions/, not db_migrations/versions/
    (the audit's old path; the repo uses alembic/versions/).
  * additionally drops chk_centroid_size / chk_embedding_size (added in 0002,
    re-sized in 0005). The spec is unaware of them; they reference the dropped
    `centroid` column and must go with it.
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_CENTROID_BYTES = 8192  # 2048 float32 (resnet50_msmt17) — used by downgrade only


def upgrade() -> None:
    # ── local_centroids ───────────────────────────────────────────────────────
    # Empty first: old single-centroid rows are incompatible with the packed
    # layout, and an empty table lets `embeddings NOT NULL` be added defaultless.
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

    # ── global_embeddings ─────────────────────────────────────────────────────
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
    # Reverse: drop the packed-store columns and restore a single centroid BYTEA.
    # Tables are emptied because the packed layout cannot be coerced back to one
    # 8192-byte centroid; centroid is then re-added NOT NULL on an empty table,
    # and the size CHECK constraint restored at the resnet50_msmt17 width.
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
