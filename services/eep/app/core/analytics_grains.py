"""Grain resolution + bucket SQL helpers for the analytics read API (E1).

`resolve_grain` turns (from, to, granularity) into the precomputed grain to read.
The discipline (see analytics 00-overview "non-additivity rule"): each grain reads
its OWN precomputed table and non-additive metrics are never summed at read time.
"""
from datetime import date

from fastapi import HTTPException

MAX_RANGE_DAYS = 730
_VALID = {"day", "week", "month"}

STORE_TABLE = {
    "day": "analytics.daily_store_summary",
    "week": "analytics.weekly_store_summary",
    "month": "analytics.monthly_store_summary",
}
ZONE_TABLE = {
    "day": "analytics.daily_zone_summary",
    "week": "analytics.weekly_zone_summary",
    "month": "analytics.monthly_zone_summary",
}
EMP_TABLE = {
    "day": "analytics.daily_employee_summary",
    "week": "analytics.weekly_employee_summary",
    "month": "analytics.monthly_employee_summary",
}


def _bad_range(msg: str, code: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": msg, "code": code})


def validate_range(from_date: date, to_date: date) -> None:
    """Range checks shared by all endpoints (incl. those without a grain knob)."""
    if from_date > to_date:
        raise _bad_range("from must be <= to", "INVALID_RANGE")
    if (to_date - from_date).days > MAX_RANGE_DAYS:
        raise _bad_range(f"range exceeds {MAX_RANGE_DAYS} days", "RANGE_TOO_LARGE")


def resolve_grain(from_date: date, to_date: date, granularity: str | None) -> str:
    """Resolve to a concrete grain ('day'|'week'|'month'). 'auto' picks by span."""
    validate_range(from_date, to_date)
    span = (to_date - from_date).days
    g = (granularity or "auto").lower()
    if g == "auto":
        if span <= 31:
            return "day"
        if span <= 182:
            return "week"
        return "month"
    if g not in _VALID:
        raise _bad_range("granularity must be one of day|week|month|auto", "INVALID_GRANULARITY")
    return g


# ── bucket_start + range-filter SQL by grain ────────────────────────────────
# Zone/employee weekly+monthly tables store only iso/year-month keys (no
# *_start_date column), so the bucket Monday/1st is computed. make_date(y,1,4)
# is always inside ISO week 1, so subtracting (isodow-1) days yields that week's
# Monday; add (iso_week-1) weeks for the target week.
_WEEK_START = (
    "(make_date(iso_year, 1, 4) "
    "- ((EXTRACT(ISODOW FROM make_date(iso_year, 1, 4))::int - 1) * INTERVAL '1 day') "
    "+ ((iso_week - 1) * INTERVAL '7 days'))::date"
)
_MONTH_START = "make_date(year, month, 1)"


def computed_bucket_start(grain: str) -> str:
    return {"day": "date", "week": _WEEK_START, "month": _MONTH_START}[grain]


def computed_range_filter(grain: str) -> str:
    """Range filter for tables keyed on iso/year-month (zone/employee rollups)."""
    if grain == "day":
        return "date BETWEEN :from_d AND :to_d"
    bs = computed_bucket_start(grain)
    if grain == "week":
        return f"{bs} <= :to_d AND ({bs} + INTERVAL '6 days') >= :from_d"
    return f"{bs} <= :to_d AND ({bs} + INTERVAL '1 month') > :from_d"


def store_bucket_start(grain: str) -> str:
    """Store-summary tables carry their own start-date column — use it directly."""
    return {"day": "date", "week": "week_start_date", "month": "month_start_date"}[grain]


def store_range_filter(grain: str) -> str:
    if grain == "day":
        return "date BETWEEN :from_d AND :to_d"
    if grain == "week":
        return "week_start_date <= :to_d AND (week_start_date + INTERVAL '6 days') >= :from_d"
    return "month_start_date <= :to_d AND (month_start_date + INTERVAL '1 month') > :from_d"
