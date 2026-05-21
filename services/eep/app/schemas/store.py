import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class CreateStoreRequest(BaseModel):
    name: str
    slug: str
    timezone: str = "Asia/Beirut"
    address: str | None = None
    currency: str = "USD"

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError("Slug must contain only lowercase letters, digits, and hyphens")
        return v

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, v: str) -> str:
        if v not in ("USD", "LBP"):
            raise ValueError("Currency must be USD or LBP")
        return v


class StoreListItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    active_version_label: str | None = None
    section_count: int = 0
    camera_count: int = 0


class StoreDetail(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    address: str | None
    currency: str
    status: str
    logo_url: str | None = None
    operating_hours: dict | None = None
    created_at: datetime
    updated_at: datetime


class PatchStoreRequest(BaseModel):
    name: str | None = None
    address: str | None = None
    timezone: str | None = None
    currency: str | None = None
    operating_hours: dict | None = None
    logo_s3_key: str | None = None
