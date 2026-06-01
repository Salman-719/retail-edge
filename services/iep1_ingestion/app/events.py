from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FrameReference(BaseModel):
    uri: str
    frame_index: int | None = Field(None, ge=0)
    timestamp_sec: float | None = Field(None, ge=0)
    width: int | None = Field(None, ge=1)
    height: int | None = Field(None, ge=1)


class SegmentReference(BaseModel):
    uri: str
    start_ts: datetime | None = None
    duration_sec: float | None = Field(None, ge=0)


class FrameRefEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: Literal["vision.frame_ref.v1"] = "vision.frame_ref.v1"
    schema_version: Literal["1.0"] = "1.0"
    store_id: uuid.UUID
    version_id: uuid.UUID
    section_id: uuid.UUID
    camera_id: uuid.UUID
    camera_config_id: uuid.UUID
    source_ts: datetime
    sequence: int = Field(ge=0)
    frame_ref: FrameReference
    segment_ref: SegmentReference | None = None

    def event_key(self) -> str:
        return str(self.camera_id)

    def to_event_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
