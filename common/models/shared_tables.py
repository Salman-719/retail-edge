"""Shared/demo tables.

``camera_calibrations`` is a flat, demo-oriented calibration table used by the
M6 seed tool and the e2e/demo path. Production IEP2 reads the richer
``calibrations``/``camera_configs``/``zones`` tables (owned by EEP) via the
calibration adapter in ``services/iep2_vision/app/calibration.py``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base


class CameraCalibration(Base):
    """Homography + zones per camera (demo/seed). Homography is a flat 9-element
    (3x3 row-major) array; the 9-length constraint is validated in application
    code on load, not by the column type."""

    __tablename__ = "camera_calibrations"

    cam_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    homography: Mapped[list[float]] = mapped_column(ARRAY(DOUBLE_PRECISION), nullable=False)
    zone_polygons: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_camera_calibrations_store", "store_id"),)
