"""Initial schema — all RetailVision tables.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "floor_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("s3_key", sa.String(1000)),
        sa.Column("width_px", sa.Integer()),
        sa.Column("height_px", sa.Integer()),
        sa.Column("origin_x", sa.Float()),
        sa.Column("origin_y", sa.Float()),
        sa.Column("scale_point1_x", sa.Float()),
        sa.Column("scale_point1_y", sa.Float()),
        sa.Column("scale_point2_x", sa.Float()),
        sa.Column("scale_point2_y", sa.Float()),
        sa.Column("real_world_distance_m", sa.Float()),
        sa.Column("pixels_per_meter", sa.Float()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "zones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "obstacles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(100)),
        sa.Column("gallery_embeddings", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "cameras",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position_x", sa.Float()),
        sa.Column("position_y", sa.Float()),
        sa.Column("height_meters", sa.Float()),
        sa.Column("rtsp_url", sa.String(1000)),
        sa.Column("video_s3_key", sa.String(1000)),
        sa.Column("video_duration", sa.Float()),
        sa.Column("video_fps", sa.Float()),
        sa.Column("video_width", sa.Integer()),
        sa.Column("video_height", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "calibrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("correspondences", sa.JSON()),
        sa.Column("homography_matrix", sa.JSON()),
        sa.Column("reprojection_error", sa.Float()),
        sa.Column("status", sa.String(50)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "tracking_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trajectory_data", sa.JSON()),
        sa.Column("zone_occupancy", sa.JSON()),
        sa.Column("heatmap_s3_key", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "shifts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "tracking_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id")),
        sa.Column("person_id", sa.String(100)),
        sa.Column("zone_id", sa.String(36), sa.ForeignKey("zones.id")),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("floor_x", sa.Float()),
        sa.Column("floor_y", sa.Float()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), server_default="active"),
        sa.Column("data", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "analytics_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("time_range_start", sa.DateTime()),
        sa.Column("time_range_end", sa.DateTime()),
        sa.Column("result", sa.JSON()),
        sa.Column("s3_key", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("analytics_results")
    op.drop_table("alerts")
    op.drop_table("tracking_history")
    op.drop_table("shifts")
    op.drop_table("tracking_results")
    op.drop_table("calibrations")
    op.drop_table("cameras")
    op.drop_table("employees")
    op.drop_table("obstacles")
    op.drop_table("zones")
    op.drop_table("floor_plans")
    op.drop_table("stores")
