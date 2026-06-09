"""Ensure camera-zone coverage exists for IEP3 spatial reconciliation.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-09

Fresh databases already get this table from schema.sql. This migration keeps
upgraded databases safe because the reconfig-edge IEP3 camera graph reads it on
every reconciliation batch.
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_zone_coverage (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            camera_config_id UUID NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
            zone_id          UUID NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
            coverage_percent FLOAT,
            computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT unique_camera_zone UNIQUE (camera_config_id, zone_id)
        );
        CREATE INDEX IF NOT EXISTS idx_camera_zone_coverage_camera
            ON camera_zone_coverage(camera_config_id);
        CREATE INDEX IF NOT EXISTS idx_camera_zone_coverage_zone
            ON camera_zone_coverage(zone_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS camera_zone_coverage")
