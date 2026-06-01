import datetime
import uuid
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator


class ScheduleCreate(BaseModel):
    camera_config_id: uuid.UUID
    days_of_week: List[int]
    start_time: datetime.time
    end_time: datetime.time
    is_active: bool = True

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v: List[int]) -> List[int]:
        for d in v:
            if d < 0 or d > 6:
                raise ValueError(f"days_of_week values must be 0–6, got {d}")
        if len(v) != len(set(v)):
            raise ValueError("days_of_week must not contain duplicates")
        return v

    @model_validator(mode="after")
    def validate_time_order(self) -> "ScheduleCreate":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be strictly before end_time")
        return self


class ScheduleUpdate(BaseModel):
    days_of_week: Optional[List[int]] = None
    start_time: Optional[datetime.time] = None
    end_time: Optional[datetime.time] = None
    is_active: Optional[bool] = None

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        for d in v:
            if d < 0 or d > 6:
                raise ValueError(f"days_of_week values must be 0–6, got {d}")
        if len(v) != len(set(v)):
            raise ValueError("days_of_week must not contain duplicates")
        return v

    @model_validator(mode="after")
    def validate_time_order(self) -> "ScheduleUpdate":
        if self.start_time is not None and self.end_time is not None:
            if self.start_time >= self.end_time:
                raise ValueError("start_time must be strictly before end_time")
        return self


class ScheduleResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    camera_config_id: uuid.UUID
    days_of_week: List[int]
    start_time: datetime.time
    end_time: datetime.time
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class TriggerRequest(BaseModel):
    action: str

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ("start", "stop"):
            raise ValueError("action must be 'start' or 'stop'")
        return v
