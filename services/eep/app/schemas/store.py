import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class CreateStoreRequest(BaseModel):
    name: str
    slug: str
    address: str

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError("Slug must contain only lowercase letters, digits, and hyphens")
        return v

    @field_validator("address")
    @classmethod
    def address_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Address is required")
        return v.strip()


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
    address: str | None
    status: str
    logo_url: str | None = None
    operating_hours: dict | None = None
    created_at: datetime
    updated_at: datetime


class PatchStoreRequest(BaseModel):
    name: str | None = None
    address: str | None = None
    operating_hours: dict | None = None
    logo_s3_key: str | None = None

    @field_validator("address")
    @classmethod
    def address_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Address cannot be blank")
        return v.strip() if v else v
