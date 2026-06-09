"""Alert-rule CRUD schemas (D3).

Pydantic carries field shape; the cross-field + DB-ownership validation (per-type
required fields, cooldown >= threshold, zone/employee ownership) lives in the
router so create and partial-update share one source of truth and return 422.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel

RULE_TYPES = {"queue_buildup", "staff_absence_zone", "staff_absence_employee"}
SEVERITIES = {"low", "medium", "high", "critical"}


class AlertRuleCreate(BaseModel):
    type: str
    name: str
    severity: str = "medium"
    is_active: bool = True
    threshold_minutes: int
    cooldown_minutes: int = 30
    followup_interval_minutes: int = 5
    people_threshold: int | None = None
    min_employees: int | None = None
    employee_id: uuid.UUID | None = None
    only_during_shift: bool = True
    zone_ids: list[uuid.UUID] = []


class AlertRuleUpdate(BaseModel):
    # All optional: None = leave unchanged. zone_ids=[] explicitly clears zones.
    name: str | None = None
    severity: str | None = None
    is_active: bool | None = None
    threshold_minutes: int | None = None
    cooldown_minutes: int | None = None
    followup_interval_minutes: int | None = None
    people_threshold: int | None = None
    min_employees: int | None = None
    employee_id: uuid.UUID | None = None
    only_during_shift: bool | None = None
    zone_ids: list[uuid.UUID] | None = None


class ZoneRef(BaseModel):
    id: uuid.UUID
    name: str


class AlertRuleResponse(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    severity: str
    is_active: bool
    threshold_minutes: int
    cooldown_minutes: int
    followup_interval_minutes: int
    only_during_shift: bool
    people_threshold: int | None = None
    min_employees: int | None = None
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None
    zones: list[ZoneRef] = []
    created_at: datetime
    updated_at: datetime
