"""Add 'tps' to calibrations.method CHECK constraint.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-07

Adds TPS (Thin-Plate Spline) as a valid calibration method. Idempotent.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE calibrations DROP CONSTRAINT IF EXISTS calibrations_method_check;
        ALTER TABLE calibrations ADD CONSTRAINT calibrations_method_check
            CHECK (method IN ('homography', 'calibration_files', 'pnp', 'tps'));

        ALTER TABLE calibrations DROP CONSTRAINT IF EXISTS verified_requires_computation;
        ALTER TABLE calibrations ADD CONSTRAINT verified_requires_computation
            CHECK (
                status != 'verified' OR
                rms_reprojection_error IS NOT NULL OR
                intrinsic_matrix IS NOT NULL OR
                coverage_score IS NOT NULL
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE calibrations DROP CONSTRAINT IF EXISTS calibrations_method_check;
        ALTER TABLE calibrations ADD CONSTRAINT calibrations_method_check
            CHECK (method IN ('homography', 'calibration_files', 'pnp'));

        ALTER TABLE calibrations DROP CONSTRAINT IF EXISTS verified_requires_computation;
        ALTER TABLE calibrations ADD CONSTRAINT verified_requires_computation
            CHECK (
                status != 'verified' OR
                rms_reprojection_error IS NOT NULL OR
                intrinsic_matrix IS NOT NULL
            );
        """
    )
