import uuid
from datetime import datetime, time
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


VALID_SHIFT_STATUSES = {"scheduled", "active", "completed", "absent", "cancelled"}
VALID_ATTENDANCE = {"scheduled", "present", "absent", "on_break"}
VALID_BREAK_TYPES = {"scheduled", "taken"}


# ── Shift Patterns ────────────────────────────────────────────────────────────

class CreateShiftPatternRequest(BaseModel):
    employee_id: uuid.UUID
    section_id: uuid.UUID
    # 0=Mon … 6=Sun
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time
    break_duration_min: int = Field(0, ge=0, le=480)

    @model_validator(mode="after")
    def end_after_start(self) -> "CreateShiftPatternRequest":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class PatchShiftPatternRequest(BaseModel):
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    break_duration_min: Optional[int] = Field(None, ge=0, le=480)
    is_active: Optional[bool] = None


class ShiftPatternResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    section_id: uuid.UUID
    day_of_week: int
    start_time: time
    end_time: time
    break_duration_min: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Shift Instances ───────────────────────────────────────────────────────────

class CreateShiftInstanceRequest(BaseModel):
    employee_id: uuid.UUID
    section_id: uuid.UUID
    scheduled_start: datetime
    scheduled_end: datetime
    shift_pattern_id: Optional[uuid.UUID] = None
    break_duration_min: int = Field(0, ge=0, le=480)
    status: str = "scheduled"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_SHIFT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(VALID_SHIFT_STATUSES)}")
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> "CreateShiftInstanceRequest":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class PatchShiftInstanceRequest(BaseModel):
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    break_duration_min: Optional[int] = Field(None, ge=0, le=480)
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_SHIFT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(VALID_SHIFT_STATUSES)}")
        return v


class ShiftInstanceResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    section_id: uuid.UUID
    shift_pattern_id: Optional[uuid.UUID]
    scheduled_start: datetime
    scheduled_end: datetime
    break_duration_min: int
    actual_start: Optional[datetime]
    actual_end: Optional[datetime]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Assignments ───────────────────────────────────────────────────────────────

class PatchAssignmentRequest(BaseModel):
    attendance_status: str

    @field_validator("attendance_status")
    @classmethod
    def validate_attendance(cls, v: str) -> str:
        if v not in VALID_ATTENDANCE:
            raise ValueError(f"attendance_status must be one of: {', '.join(VALID_ATTENDANCE)}")
        return v


class AssignmentResponse(BaseModel):
    id: uuid.UUID
    shift_id: uuid.UUID
    employee_id: uuid.UUID
    attendance_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Breaks ────────────────────────────────────────────────────────────────────

class CreateBreakRequest(BaseModel):
    break_start: datetime
    break_end: Optional[datetime] = None
    break_type: str = "taken"

    @field_validator("break_type")
    @classmethod
    def validate_break_type(cls, v: str) -> str:
        if v not in VALID_BREAK_TYPES:
            raise ValueError(f"break_type must be one of: {', '.join(VALID_BREAK_TYPES)}")
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> "CreateBreakRequest":
        if self.break_end is not None and self.break_end <= self.break_start:
            raise ValueError("break_end must be after break_start")
        return self


class PatchBreakRequest(BaseModel):
    break_end: Optional[datetime] = None
    break_type: Optional[str] = None

    @field_validator("break_type")
    @classmethod
    def validate_break_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_BREAK_TYPES:
            raise ValueError(f"break_type must be one of: {', '.join(VALID_BREAK_TYPES)}")
        return v


class BreakResponse(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    break_start: datetime
    break_end: Optional[datetime]
    break_type: str
    created_at: datetime

    model_config = {"from_attributes": True}
