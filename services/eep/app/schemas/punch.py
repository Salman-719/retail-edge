"""Punch-in event schemas (employee-linking, S3)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class PunchEventRequest(BaseModel):
    """Production-shaped punch payload. Provide exactly one employee identifier.

    A real punch machine knows the badge `employee_code`; `employee_id` is accepted
    for callers that already hold the UUID. `punched_at` defaults to server now (UTC).
    """

    employee_code: str | None = None
    employee_id: uuid.UUID | None = None
    punched_at: datetime | None = None

    @model_validator(mode="after")
    def exactly_one_identifier(self) -> "PunchEventRequest":
        if (self.employee_id is None) == (self.employee_code is None):
            raise ValueError("provide exactly one of employee_id or employee_code")
        return self


class PunchEventResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    employee_id: uuid.UUID
    punched_at_ms: int
    source: str
    status: str
    linked_global_id: uuid.UUID | None = None
    match_distance_m: float | None = None

    model_config = {"from_attributes": True}


class DevPunchRequest(BaseModel):
    """DEBUG-only dev trigger payload (dev_pipeline)."""

    store_id: uuid.UUID
    employee_id: uuid.UUID
    at: datetime | None = None
