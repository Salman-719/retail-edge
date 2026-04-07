"""Re-export all schemas for convenience."""
from app.schemas.common import HealthResponse, Point
from app.schemas.store import StoreCreate, StoreResponse, ScaleConfig, FloorPlanResponse
from app.schemas.zone import (
    ZoneCreate, ZoneUpdate, ZoneResponse,
    ObstacleCreate, ObstacleUpdate, ObstacleResponse,
)
from app.schemas.camera import (
    CameraCreate, CameraUpdate, CameraResponse,
    CalibrationRequest, CalibrationResponse,
    CorrespondencePoint, ProjectSave,
)

__all__ = [
    "HealthResponse", "Point",
    "StoreCreate", "StoreResponse", "ScaleConfig", "FloorPlanResponse",
    "ZoneCreate", "ZoneUpdate", "ZoneResponse",
    "ObstacleCreate", "ObstacleUpdate", "ObstacleResponse",
    "CameraCreate", "CameraUpdate", "CameraResponse",
    "CalibrationRequest", "CalibrationResponse",
    "CorrespondencePoint", "ProjectSave",
]
