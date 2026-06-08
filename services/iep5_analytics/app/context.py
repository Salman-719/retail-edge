"""Run context for one IEP5 invocation: derived time bounds, active version /
floor-plan origin, and the ISO week / calendar month rollup parameters.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass
class RunContext:
    store_id: uuid.UUID
    shift_date: date

    # Calendar-day window (UTC) for the shift_date.
    day_start_ms: int
    day_end_ms: int

    # Actual shift bounds from global_tracking_history (None when the shift is empty).
    shift_start_ms: int | None
    shift_end_ms: int | None

    # Active config + floor-plan origin (for heatmap grid).
    version_id: uuid.UUID | None
    origin_x: float
    origin_y: float

    # Tunables (copied from settings).
    cell_size_m: float
    passthrough_ms: int
    dead_threshold: int
    dead_duration_ms: int

    # Rollup parameters.
    iso_year: int
    iso_week: int
    week_start_date: date
    is_week_complete: bool
    year: int
    month: int
    month_start_date: date
    is_month_complete: bool

    @property
    def has_data(self) -> bool:
        return self.shift_start_ms is not None and self.shift_end_ms is not None


def day_bounds_ms(shift_date: date) -> tuple[int, int]:
    start = datetime(shift_date.year, shift_date.month, shift_date.day, tzinfo=timezone.utc)
    day_start_ms = int(start.timestamp() * 1000)
    return day_start_ms, day_start_ms + 86_400_000


def rollup_params(shift_date: date):
    iso_year, iso_week, iso_weekday = shift_date.isocalendar()
    week_start_date = shift_date - timedelta(days=iso_weekday - 1)
    is_week_complete = iso_weekday == 7

    month_start_date = shift_date.replace(day=1)
    last_day_of_month = (month_start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    is_month_complete = shift_date == last_day_of_month

    return (
        iso_year, iso_week, week_start_date, is_week_complete,
        shift_date.year, shift_date.month, month_start_date, is_month_complete,
    )
