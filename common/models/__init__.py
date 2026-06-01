"""SQLAlchemy ORM models for the IEP2/IEP3 subsystem.

These models share their own ``Base`` (see ``base.py``) so tests can
``create_all`` them against a throwaway database. The authoritative DDL for
production lives in ``services/eep/schema.sql`` (applied at Postgres init); this
ORM layer is what application code queries against and must stay in sync with it.
"""

from common.models.base import Base
from common.models.iep2_tables import LocalCentroid, LocalEmbedding, TrackingHistory
from common.models.iep3_tables import (
    GlobalEmbedding,
    GlobalGalleryEmbedding,
    GlobalIdentity,
    GlobalLocalMapping,
    GlobalTrackingHistory,
)
from common.models.shared_tables import CameraCalibration

__all__ = [
    "Base",
    "TrackingHistory",
    "LocalEmbedding",
    "LocalCentroid",
    "GlobalIdentity",
    "GlobalLocalMapping",
    "GlobalEmbedding",
    "GlobalGalleryEmbedding",
    "GlobalTrackingHistory",
    "CameraCalibration",
]
