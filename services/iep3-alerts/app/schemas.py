"""IEP3 — Alerts & Rule Engine Service: I/O contract.

All request bodies, query parameters, and response payloads are declared here so
every endpoint has an explicit, typed, documented contract.

Endpoint catalogue
------------------

POST /alerts/rules
    Input :  AlertRuleCreate
    Output:  AlertRule                        (200)

GET  /alerts/rules
    Query :  store_id:str|None=None
    Output:  List[AlertRule]                  (200)

DELETE /alerts/rules/{rule_id}
    Output:  —                                (204)
    Errors:  404 rule not found

POST /alerts/evaluate
    Input :  TrackingEvent                    (sent by IEP2 after tracking job)
    Output:  List[AlertResult]                (200)

GET  /alerts/{store_id}
    Output:  List[Alert]                      (200)

PATCH /alerts/{alert_id}
    Input :  AlertUpdate
    Output:  Alert                            (200)
    Errors:  404 alert not found

GET  /health
    Output:  HealthResponse                   (200)
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    service: str = "iep3-alerts"
    status: str = "ok"


# ── Shared primitives ─────────────────────────────────────────────────────────

RuleType = Literal["zone_dwell", "zone_crowding", "no_staff"]
Severity = Literal["info", "warning", "critical"]
AlertStatus = Literal["active", "acknowledged", "resolved"]


class ZoneOccupancy(BaseModel):
    """Dwell statistics for a single zone during a tracking run."""
    seconds: float = Field(..., ge=0)
    percent: float = Field(..., ge=0, le=100)


# ── Rules ─────────────────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    """Define a new alerting rule."""
    store_id: str
    name: str
    type: RuleType
    zone_name: Optional[str] = None
    threshold_seconds: Optional[float] = Field(None, ge=0, description="For dwell-time rules")
    threshold_count: Optional[int] = Field(None, ge=0, description="For crowding rules")
    enabled: bool = True


class AlertRule(AlertRuleCreate):
    id: str
    created_at: datetime


# ── Evaluation ────────────────────────────────────────────────────────────────

class TrackingEvent(BaseModel):
    """Sent by IEP2 after a tracking job completes."""
    store_id: str
    camera_id: str
    zone_occupancy: Dict[str, ZoneOccupancy] = Field(default_factory=dict)
    trajectory: List[Dict[str, Any]] = Field(default_factory=list)
    total_frames: int = Field(0, ge=0)
    fps: float = Field(0.0, ge=0)


class AlertResult(BaseModel):
    """An alert emitted when a rule condition is met."""
    rule_id: str
    rule_name: str
    type: RuleType
    severity: Severity
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)


# ── Alerts ────────────────────────────────────────────────────────────────────

class Alert(BaseModel):
    id: str
    store_id: str
    rule_id: Optional[str] = None
    type: RuleType
    severity: Severity
    status: AlertStatus
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AlertUpdate(BaseModel):
    status: Optional[AlertStatus] = None
