"""Analytics read-API response models (E1).

Durations stay in milliseconds (ints); the frontend formats. Dates are ISO
YYYY-MM-DD. Every endpoint returns the same envelope: {store_id, grain, from, to,
rows}. Fields absent at a coarser grain (e.g. peak_occupancy_at_ms only exists
daily) are returned as null rather than fabricated.
"""
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class _Envelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    store_id: uuid.UUID
    grain: str
    from_: date = Field(alias="from")
    to: date


# ── /store-series ───────────────────────────────────────────────────────────
class StoreSeriesRow(BaseModel):
    bucket_start: date
    total_visits: int
    unique_visitors: int
    avg_visit_duration_ms: int | None = None
    median_visit_duration_ms: int | None = None
    peak_occupancy: int | None = None
    peak_occupancy_at_ms: int | None = None  # daily only
    dead_period_count: int
    dead_period_total_ms: int | None = None  # daily only
    is_complete: bool


class StoreSeriesResponse(_Envelope):
    rows: list[StoreSeriesRow]


# ── /zones ──────────────────────────────────────────────────────────────────
class ZoneRow(BaseModel):
    zone_id: uuid.UUID
    zone_name: str
    bucket_start: date
    unique_visitors: int
    total_transitions: int | None = None  # daily only
    avg_dwell_ms: int | None = None
    median_dwell_ms: int | None = None
    max_concurrent: int | None = None  # daily only
    passthrough_count: int
    engagement_count: int
    alert_trigger_count: int | None = None  # daily only
    is_complete: bool


class ZonesResponse(_Envelope):
    rows: list[ZoneRow]


# ── /composition ────────────────────────────────────────────────────────────
class CompositionRow(BaseModel):
    bucket_start: date
    customers: int
    staff: int
    is_complete: bool


class CompositionResponse(_Envelope):
    rows: list[CompositionRow]


# ── /distribution (daily-derived; grain echoed as 'day') ────────────────────
class DistributionRow(BaseModel):
    bucket_label: str
    bucket_min_ms: int
    bucket_max_ms: int | None = None  # open-ended top bucket
    visit_count: int


class DistributionResponse(_Envelope):
    rows: list[DistributionRow]


# ── /employees ──────────────────────────────────────────────────────────────
class EmployeeRow(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    bucket_start: date
    scheduled_duration_ms: int | None = None
    present_duration_ms: int | None = None
    presence_ratio: float | None = None
    zone_punctuality_delay_ms: int | None = None
    unassigned_zone_time_ms: int | None = None  # daily only
    is_complete: bool


class EmployeesResponse(_Envelope):
    rows: list[EmployeeRow]


# ── /flow-matrix (daily-derived; grain echoed as 'day') ─────────────────────
class FlowMatrixRow(BaseModel):
    from_zone_id: uuid.UUID | None = None
    from_zone_name: str | None = None
    to_zone_id: uuid.UUID | None = None
    to_zone_name: str | None = None
    transition_count: int
    probability: float | None = None


class FlowMatrixResponse(_Envelope):
    rows: list[FlowMatrixRow]


# ── /heatmap (E3) ───────────────────────────────────────────────────────────
class HeatmapFloorPlan(BaseModel):
    """Projection metadata so the frontend draws cells with the SAME world→pixel
    transform it uses for zones/cameras — never a second formula."""

    origin_x: float | None = None
    origin_y: float | None = None
    pixels_per_meter: float | None = None
    world_x_min: float | None = None
    world_x_max: float | None = None
    world_y_min: float | None = None
    world_y_max: float | None = None
    width_px: int | None = None
    height_px: int | None = None
    display_url: str | None = None
    image_uploaded: bool


class HeatmapCell(BaseModel):
    grid_x: int
    grid_y: int
    hit_count: int
    intensity: float  # hit_count / max_hit_count, 0..1
    world_x_min: float
    world_x_max: float
    world_y_min: float
    world_y_max: float


class HeatmapResponse(_Envelope):
    version_id: uuid.UUID | None = None
    cell_size_m: float
    max_hit_count: int
    floor_plan: HeatmapFloorPlan | None = None
    cells: list[HeatmapCell]
