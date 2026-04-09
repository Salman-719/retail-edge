"""Employee and Shift Pydantic schemas."""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel


class EmployeeCreate(BaseModel):
    id: Optional[str] = None
    name: str
    role: Optional[str] = None


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None


class EmployeeResponse(BaseModel):
    id: str
    store_id: str
    name: str
    role: Optional[str] = None
    gallery_embeddings: Optional[list] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ShiftCreate(BaseModel):
    start_time: datetime
    end_time: Optional[datetime] = None


class ShiftResponse(BaseModel):
    id: str
    employee_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
