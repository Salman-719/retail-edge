import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


VALID_ROLES = {
    "cashier", "shelf_stocker", "supervisor", "security",
    "cleaner", "manager", "delivery", "customer_service",
}

VALID_ENROLLMENT_STATUSES = {"pending", "enrolled", "needs_update"}


class CreateEmployeeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    role: Optional[str] = Field(None, max_length=100)
    employee_code: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class PatchEmployeeRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    role: Optional[str] = Field(None, max_length=100)
    employee_code: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    enrollment_status: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v

    @field_validator("enrollment_status")
    @classmethod
    def validate_enrollment(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_ENROLLMENT_STATUSES:
            raise ValueError(f"enrollment_status must be one of: {', '.join(VALID_ENROLLMENT_STATUSES)}")
        return v


class EmployeeResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    name: str
    role: Optional[str]
    employee_code: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    enrollment_status: str
    last_enrolled_at: Optional[datetime]
    is_on_shift: bool
    break_status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
