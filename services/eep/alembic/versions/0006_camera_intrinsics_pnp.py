"""Camera intrinsics + PnP calibration foundation (M7-S1).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-06

Replaces the (top-down-only) homography approach with a 3D projection
foundation. Adds intrinsic parameters to physical_cameras and a 'pnp' method to
the calibrations method enum. No runtime projection changes here — this only
prepares the schema and intrinsics. Idempotent and safe on fresh or existing
databases.

stream_width / stream_height already exist from the Domain 9 migration; they are
NOT re-added here.
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Intrinsic fields on physical_cameras.
    op.execute(
        """
        ALTER TABLE physical_cameras
            ADD COLUMN IF NOT EXISTS lens_focal_length_mm  FLOAT,
            ADD COLUMN IF NOT EXISTS h_fov_deg             FLOAT,
            ADD COLUMN IF NOT EXISTS v_fov_deg             FLOAT,
            ADD COLUMN IF NOT EXISTS fx                    FLOAT,
            ADD COLUMN IF NOT EXISTS fy                    FLOAT,
            ADD COLUMN IF NOT EXISTS cx                    FLOAT,
            ADD COLUMN IF NOT EXISTS cy                    FLOAT,
            ADD COLUMN IF NOT EXISTS dist_coeffs           JSONB,
            ADD COLUMN IF NOT EXISTS intrinsics_source     VARCHAR(20)
                                     CHECK (intrinsics_source IN ('estimated', 'chessboard'))
        """
    )

    # Add 'pnp' to the calibrations method enum.
    op.execute("ALTER TABLE calibrations DROP CONSTRAINT IF EXISTS calibrations_method_check")
    op.execute(
        """
        ALTER TABLE calibrations
            ADD CONSTRAINT calibrations_method_check
            CHECK (method IN ('homography', 'calibration_files', 'pnp'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE calibrations DROP CONSTRAINT IF EXISTS calibrations_method_check")
    op.execute(
        """
        ALTER TABLE calibrations
            ADD CONSTRAINT calibrations_method_check
            CHECK (method IN ('homography', 'calibration_files'))
        """
    )
    op.execute(
        """
        ALTER TABLE physical_cameras
            DROP COLUMN IF EXISTS lens_focal_length_mm,
            DROP COLUMN IF EXISTS h_fov_deg,
            DROP COLUMN IF EXISTS v_fov_deg,
            DROP COLUMN IF EXISTS fx,
            DROP COLUMN IF EXISTS fy,
            DROP COLUMN IF EXISTS cx,
            DROP COLUMN IF EXISTS cy,
            DROP COLUMN IF EXISTS dist_coeffs,
            DROP COLUMN IF EXISTS intrinsics_source
        """
    )
