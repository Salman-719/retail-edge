"""Add calibration-files method support — stores.onboarding_method, floor_plans.world_bounds,
calibrations intrinsic/extrinsic columns.

Revision ID: 003
Revises: 002
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── stores: track which onboarding method was used ────────────────────────
    op.add_column(
        "stores",
        sa.Column("onboarding_method", sa.String(20), server_default="standard"),
    )

    # ── floor_plans: virtual canvas bounds for Method 2 (no floor plan image) ─
    op.add_column("floor_plans", sa.Column("world_x_min", sa.Float(), nullable=True))
    op.add_column("floor_plans", sa.Column("world_x_max", sa.Float(), nullable=True))
    op.add_column("floor_plans", sa.Column("world_y_min", sa.Float(), nullable=True))
    op.add_column("floor_plans", sa.Column("world_y_max", sa.Float(), nullable=True))

    # ── calibrations: intrinsic/extrinsic data for Method 2 ──────────────────
    # Discriminator: 'homography' (default, existing rows) | 'calibration_files'
    op.add_column(
        "calibrations",
        sa.Column("method", sa.String(20), server_default="homography"),
    )
    # 3×3 intrinsic matrix K stored as JSON [[row0],[row1],[row2]]
    op.add_column("calibrations", sa.Column("intrinsic_matrix", sa.JSON(), nullable=True))
    # Distortion coefficients [k1, k2, p1, p2, k3, ...]
    op.add_column("calibrations", sa.Column("dist_coeffs", sa.JSON(), nullable=True))
    # 3×3 rotation matrix R (post-Rodrigues conversion from rvec)
    op.add_column("calibrations", sa.Column("rotation_matrix", sa.JSON(), nullable=True))
    # Translation vector [tx, ty, tz]
    op.add_column("calibrations", sa.Column("translation_vector", sa.JSON(), nullable=True))
    # Image dimensions used during calibration
    op.add_column("calibrations", sa.Column("image_width", sa.Integer(), nullable=True))
    op.add_column("calibrations", sa.Column("image_height", sa.Integer(), nullable=True))
    # Pre-computed camera world position C = -R^T @ t (stored for fast retrieval)
    op.add_column("calibrations", sa.Column("camera_world_x", sa.Float(), nullable=True))
    op.add_column("calibrations", sa.Column("camera_world_y", sa.Float(), nullable=True))
    op.add_column("calibrations", sa.Column("camera_world_z", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("calibrations", "camera_world_z")
    op.drop_column("calibrations", "camera_world_y")
    op.drop_column("calibrations", "camera_world_x")
    op.drop_column("calibrations", "image_height")
    op.drop_column("calibrations", "image_width")
    op.drop_column("calibrations", "translation_vector")
    op.drop_column("calibrations", "rotation_matrix")
    op.drop_column("calibrations", "dist_coeffs")
    op.drop_column("calibrations", "intrinsic_matrix")
    op.drop_column("calibrations", "method")

    op.drop_column("floor_plans", "world_y_max")
    op.drop_column("floor_plans", "world_y_min")
    op.drop_column("floor_plans", "world_x_max")
    op.drop_column("floor_plans", "world_x_min")

    op.drop_column("stores", "onboarding_method")
