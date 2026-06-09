"""Live overview schemas (F1).

Positions are WORLD METRES (homography output); the frontend projects with the
shared worldToImagePx helper — the backend never projects to pixels.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel


class LiveKpis(BaseModel):
    total_people: int
    customers: int
    staff_on_floor: int
    active_alerts: int


class LivePerson(BaseModel):
    global_id: uuid.UUID
    type: str  # 'customer' | 'staff'
    world_x: float
    world_y: float
    current_zone_id: uuid.UUID | None = None
    current_zone_name: str | None = None
    employee_name: str | None = None  # null for customers
    dwell_ms: int


class LiveOverview(BaseModel):
    generated_at_ms: int
    kpis: LiveKpis
    persons: list[LivePerson]


# ── F2: camera health ────────────────────────────────────────────────────────
class CameraHealthItem(BaseModel):
    physical_camera_id: uuid.UUID
    name: str
    status: str  # raw live status: running|starting|restarting|offline|unknown|...
    last_status_ms: int | None = None  # null = never reported
    online: bool  # status == 'running'


class AgentHealth(BaseModel):
    status: str | None = None
    last_heartbeat_at: datetime | None = None
    heartbeat_age_seconds: float | None = None
    agent_version: str | None = None
    online: bool


class CameraHealth(BaseModel):
    cameras: list[CameraHealthItem]
    agent: AgentHealth
    generated_at_ms: int
