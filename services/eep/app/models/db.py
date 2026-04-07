"""Backward-compat re-export shim.

All ORM models now live in their domain files:
  app.models.store      → Store, FloorPlan
  app.models.zone       → Zone, Obstacle
  app.models.camera     → Camera, Calibration, TrackingResult
  app.models.employee   → Employee, Shift
  app.models.analytics  → TrackingHistory, Alert, AnalyticsResult

Existing code that does `from app.models import db as models` continues to work.
"""
from app.models.store import Store, FloorPlan
from app.models.zone import Zone, Obstacle
from app.models.camera import Camera, Calibration, TrackingResult
from app.models.employee import Employee, Shift
from app.models.analytics import TrackingHistory, Alert, AnalyticsResult

__all__ = [
    "Store", "FloorPlan",
    "Zone", "Obstacle",
    "Camera", "Calibration", "TrackingResult",
    "Employee", "Shift",
    "TrackingHistory", "Alert", "AnalyticsResult",
]
