"""Widen centroid byte-size constraints from 512-dim to 2048-dim embeddings.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-06

The ReID model changed from OSNet (512-dim) to resnet50_msmt17 (2048-dim).
Migration 0002 added CHECK constraints requiring centroid BYTEA to be exactly
2048 bytes (512 float32 values). resnet50_msmt17 emits 2048-dim embeddings =
2048 * 4 = 8192 bytes, which the old constraint rejects on every insert.

This migration drops the 2048-byte constraints and re-adds them at 8192 bytes.
Idempotent: DROP ... IF EXISTS, then add via the DO $$ ... EXCEPTION idiom so it
is safe on fresh DBs (schema.sql has no size constraint) and on existing ones.

NOTE: existing 512-dim rows (2048 bytes) violate the new 8192-byte constraint.
The deploy procedure clears the embedding/centroid tables before/with this
migration (dev reset or `down -v`), so no in-place data conversion is attempted.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_OLD_BYTES = 2048   # 512 float32 (OSNet)
_NEW_BYTES = 8192   # 2048 float32 (resnet50_msmt17)


def upgrade() -> None:
    # Drop the old 512-dim (2048-byte) constraints.
    op.execute(sa.text(
        "ALTER TABLE local_centroids DROP CONSTRAINT IF EXISTS chk_centroid_size"
    ))
    op.execute(sa.text(
        "ALTER TABLE global_embeddings DROP CONSTRAINT IF EXISTS chk_embedding_size"
    ))

    # Re-add at 8192 bytes = 2048 float32 values = resnet50_msmt17 embedding.
    # Guard: schema.sql already uses the post-0013 layout (embeddings column, no
    # centroid). Skip on fresh DBs where centroid never existed.
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "  WHERE table_name='local_centroids' AND column_name='centroid'"
        ") THEN "
        f"ALTER TABLE local_centroids ADD CONSTRAINT chk_centroid_size CHECK (octet_length(centroid) = {_NEW_BYTES}); "
        "END IF; "
        "END; $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "  WHERE table_name='global_embeddings' AND column_name='centroid'"
        ") THEN "
        f"ALTER TABLE global_embeddings ADD CONSTRAINT chk_embedding_size CHECK (octet_length(centroid) = {_NEW_BYTES}); "
        "END IF; "
        "END; $$"
    ))


def downgrade() -> None:
    # Revert to the 512-dim (2048-byte) constraints.
    op.execute(sa.text(
        "ALTER TABLE local_centroids DROP CONSTRAINT IF EXISTS chk_centroid_size"
    ))
    op.execute(sa.text(
        "ALTER TABLE global_embeddings DROP CONSTRAINT IF EXISTS chk_embedding_size"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "ALTER TABLE local_centroids "
        f"ADD CONSTRAINT chk_centroid_size CHECK (octet_length(centroid) = {_OLD_BYTES}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END; $$"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "ALTER TABLE global_embeddings "
        f"ADD CONSTRAINT chk_embedding_size CHECK (octet_length(centroid) = {_OLD_BYTES}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END; $$"
    ))
