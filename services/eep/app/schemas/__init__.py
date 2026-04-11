"""Re-export all schemas for convenience."""
from app.schemas.common import HealthResponse, Point
from app.schemas.store import StoreCreate, StoreResponse, ScaleConfig, FloorPlanResponse, WorldBoundsConfig
from app.schemas.zone import (
    ZoneCreate, ZoneUpdate, ZoneResponse,
    ObstacleCreate, ObstacleUpdate, ObstacleResponse,
)
from app.schemas.camera import (
    CameraCreate, CameraUpdate, CameraResponse,
    CalibrationRequest, CalibrationResponse,
    CalibrationFilesRequest, ParsedCalibrationResponse,
    CorrespondencePoint, ProjectSave,
)
from app.schemas.employee import (
    EmployeeCreate, EmployeeUpdate, EmployeeResponse,
    ShiftCreate, ShiftResponse,
)

__all__ = [
    "HealthResponse", "Point",
    "StoreCreate", "StoreResponse", "ScaleConfig", "FloorPlanResponse",
    "ZoneCreate", "ZoneUpdate", "ZoneResponse",
    "ObstacleCreate", "ObstacleUpdate", "ObstacleResponse",
    "WorldBoundsConfig",
    "CameraCreate", "CameraUpdate", "CameraResponse",
    "CalibrationRequest", "CalibrationResponse",
    "CalibrationFilesRequest", "ParsedCalibrationResponse",
    "CorrespondencePoint", "ProjectSave",
    "EmployeeCreate", "EmployeeUpdate", "EmployeeResponse",
    "ShiftCreate", "ShiftResponse",
]
