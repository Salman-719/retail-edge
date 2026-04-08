"""IEP3 — Alerts & Rule Engine schemas.

Defines the input/output contract for the alert service.

Endpoints:
  POST /alerts/rules
    Input:  AlertRuleCreate
    Output: AlertRule

  GET  /alerts/rules
    Output: List[AlertRule]

  DELETE /alerts/rules/{rule_id}
    Output: 204

  POST /alerts/evaluate
    Input:  TrackingEvent (sent by IEP2 after each tracking job)
    Output: List[AlertResult]

  GET  /alerts/{store_id}
    Output: List[Alert]

  PATCH /alerts/{alert_id}
    Input:  AlertUpdate
    Output: Alert
"""
from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel


# ── Rules ─────────────────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    """Define a new alerting rule."""
    store_id: str
    name: str
    type: str           # "zone_dwell" | "zone_crowding" | "no_staff"
    zone_name: Optional[str] = None
    threshold_seconds: Optional[float] = None   # for dwell-time rules
    threshold_count: Optional[int] = None        # for crowding rules
    enabled: bool = True


class AlertRule(AlertRuleCreate):
    id: str
    created_at: datetime


# ── Evaluation ────────────────────────────────────────────────────────────────

class TrackingEvent(BaseModel):
    """Sent by IEP2 after a tracking job completes."""
    store_id: str
    camera_id: str
    zone_occupancy: Dict[str, Dict]  # {zone_name: {seconds, percent}}
    trajectory: List[Dict]
    total_frames: int
    fps: float


class AlertResult(BaseModel):
    """An alert emitted when a rule condition is met."""
    rule_id: str
    rule_name: str
    type: str
    severity: str        # "info" | "warning" | "critical"
    message: str
    data: Dict = {}


# ── Alerts ────────────────────────────────────────────────────────────────────

class Alert(BaseModel):
    id: str
    store_id: str
    rule_id: Optional[str] = None
    type: str
    severity: str
    status: str          # "active" | "acknowledged" | "resolved"
    message: str
    data: Dict = {}
    created_at: datetime


class AlertUpdate(BaseModel):
    status: Optional[str] = None  # "acknowledged" | "resolved"
