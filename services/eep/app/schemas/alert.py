"""Alert read/resolve schemas (D1/D2).

Uniform shape over every alert type (staff_absence, queue_buildup, camera_offline,
camera_degraded) — `details` (verbatim IEP4 JSONB) carries the type-specifics, so
camera alerts added in CAT F appear with no schema change.

`severity` is copied from the firing rule by IEP4 (added in D3).
"""
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertResponse(BaseModel):
    id: uuid.UUID
    type: str
    severity: str
    zone_id: uuid.UUID | None = None
    zone_name: str | None = None
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime
    is_followup: bool
    alert_rule_id: uuid.UUID | None = None
    alert_rule_name: str | None = None
    # Resolution (null while active)
    resolved_at: datetime | None = None
    resolution: str | None = None
    resolved_by: uuid.UUID | None = None
    resolved_by_name: str | None = None


class AlertHistoryResponse(BaseModel):
    total: int
    limit: int
    offset: int
    alerts: list[AlertResponse]


# ── D7: alerts over time ─────────────────────────────────────────────────────
class AlertTimeseriesRow(BaseModel):
    bucket_start: date
    type: str
    severity: str
    count: int


class AlertTimeseriesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    store_id: uuid.UUID
    grain: str
    from_: date = Field(alias="from")
    to: date
    rows: list[AlertTimeseriesRow]
