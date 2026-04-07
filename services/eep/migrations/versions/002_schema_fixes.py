"""Schema fixes — CASCADE deletes, indexes, Zone.updated_at, TrackingResult.store_id, Shift.end_time nullable.

Revision ID: 002
Revises: 001
Create Date: 2026-04-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Zone: add updated_at ──────────────────────────────────────────────────
    op.add_column("zones", sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()))

    # ── TrackingResult: add store_id FK ───────────────────────────────────────
    op.add_column("tracking_results", sa.Column("store_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_tracking_results_store_id",
        "tracking_results", "stores",
        ["store_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_tracking_results_store_id", "tracking_results", ["store_id"])
    op.create_index("ix_tracking_results_camera_id", "tracking_results", ["camera_id"])

    # ── Shift: make end_time nullable ─────────────────────────────────────────
    op.alter_column("shifts", "end_time", nullable=True)

    # ── Fix missing CASCADE on tracking_history, alerts, analytics_results ────
    # tracking_history
    op.drop_constraint("tracking_history_store_id_fkey", "tracking_history", type_="foreignkey")
    op.create_foreign_key(
        "fk_tracking_history_store_id",
        "tracking_history", "stores",
        ["store_id"], ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("tracking_history_camera_id_fkey", "tracking_history", type_="foreignkey")
    op.create_foreign_key(
        "fk_tracking_history_camera_id",
        "tracking_history", "cameras",
        ["camera_id"], ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("tracking_history_zone_id_fkey", "tracking_history", type_="foreignkey")
    op.create_foreign_key(
        "fk_tracking_history_zone_id",
        "tracking_history", "zones",
        ["zone_id"], ["id"],
        ondelete="SET NULL",
    )

    # alerts
    op.drop_constraint("alerts_store_id_fkey", "alerts", type_="foreignkey")
    op.create_foreign_key(
        "fk_alerts_store_id",
        "alerts", "stores",
        ["store_id"], ["id"],
        ondelete="CASCADE",
    )

    # analytics_results
    op.drop_constraint("analytics_results_store_id_fkey", "analytics_results", type_="foreignkey")
    op.create_foreign_key(
        "fk_analytics_results_store_id",
        "analytics_results", "stores",
        ["store_id"], ["id"],
        ondelete="CASCADE",
    )

    # ── Indexes on FK columns ─────────────────────────────────────────────────
    op.create_index("ix_floor_plans_store_id", "floor_plans", ["store_id"])
    op.create_index("ix_zones_store_id", "zones", ["store_id"])
    op.create_index("ix_obstacles_store_id", "obstacles", ["store_id"])
    op.create_index("ix_cameras_store_id", "cameras", ["store_id"])
    op.create_index("ix_calibrations_camera_id", "calibrations", ["camera_id"])
    op.create_index("ix_employees_store_id", "employees", ["store_id"])
    op.create_index("ix_shifts_employee_id", "shifts", ["employee_id"])

    # ── Composite indexes for analytics queries ───────────────────────────────
    op.create_index("ix_tracking_history_store_ts", "tracking_history", ["store_id", "timestamp"])
    op.create_index("ix_tracking_history_camera", "tracking_history", ["camera_id"])
    op.create_index("ix_tracking_history_zone", "tracking_history", ["zone_id"])
    op.create_index("ix_alerts_store_status", "alerts", ["store_id", "status"])
    op.create_index("ix_analytics_results_store_type", "analytics_results", ["store_id", "type"])


def downgrade() -> None:
    op.drop_index("ix_analytics_results_store_type", "analytics_results")
    op.drop_index("ix_alerts_store_status", "alerts")
    op.drop_index("ix_tracking_history_zone", "tracking_history")
    op.drop_index("ix_tracking_history_camera", "tracking_history")
    op.drop_index("ix_tracking_history_store_ts", "tracking_history")
    op.drop_index("ix_shifts_employee_id", "shifts")
    op.drop_index("ix_employees_store_id", "employees")
    op.drop_index("ix_calibrations_camera_id", "calibrations")
    op.drop_index("ix_cameras_store_id", "cameras")
    op.drop_index("ix_obstacles_store_id", "obstacles")
    op.drop_index("ix_zones_store_id", "zones")
    op.drop_index("ix_floor_plans_store_id", "floor_plans")
    op.drop_index("ix_tracking_results_camera_id", "tracking_results")
    op.drop_index("ix_tracking_results_store_id", "tracking_results")

    op.drop_constraint("fk_analytics_results_store_id", "analytics_results", type_="foreignkey")
    op.create_foreign_key(None, "analytics_results", "stores", ["store_id"], ["id"])
    op.drop_constraint("fk_alerts_store_id", "alerts", type_="foreignkey")
    op.create_foreign_key(None, "alerts", "stores", ["store_id"], ["id"])
    op.drop_constraint("fk_tracking_history_zone_id", "tracking_history", type_="foreignkey")
    op.create_foreign_key(None, "tracking_history", "zones", ["zone_id"], ["id"])
    op.drop_constraint("fk_tracking_history_camera_id", "tracking_history", type_="foreignkey")
    op.create_foreign_key(None, "tracking_history", "cameras", ["camera_id"], ["id"])
    op.drop_constraint("fk_tracking_history_store_id", "tracking_history", type_="foreignkey")
    op.create_foreign_key(None, "tracking_history", "stores", ["store_id"], ["id"])

    op.drop_constraint("fk_tracking_results_store_id", "tracking_results", type_="foreignkey")
    op.drop_column("tracking_results", "store_id")
    op.alter_column("shifts", "end_time", nullable=False)
    op.drop_column("zones", "updated_at")
