"""Analytics read API (E1) — thin reads over IEP5's precomputed analytics.* rollups.

Each grain reads its OWN precomputed table; non-additive metrics (unique_visitors,
avg_*, median_*, presence_ratio, probability, peak_occupancy) are NEVER summed at
read time. Additive counts may be summed for daily-derived endpoints (distribution,
flow-matrix). Missing buckets are omitted (not zero-filled) so the frontend can tell
"no data yet" from "zero traffic". Read-only; no audit. Store-scoped via
get_store_context (super-admins reach any store via the A1 bypass).
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import analytics_grains as ag
from app.core.config import settings
from app.core.database import get_db
from app.core.s3_client import safe_presign_public
from app.middleware.store_auth import StoreContext, get_store_context
from app.models.floor_plan import FloorPlan
from app.models.version import StoreConfigVersion
from app.schemas.analytics import (
    CompositionResponse,
    CompositionRow,
    DistributionResponse,
    DistributionRow,
    EmployeeRow,
    EmployeesResponse,
    FlowMatrixResponse,
    FlowMatrixRow,
    HeatmapCell,
    HeatmapFloorPlan,
    HeatmapResponse,
    StoreSeriesResponse,
    StoreSeriesRow,
    ZoneRow,
    ZonesResponse,
)

router = APIRouter(tags=["analytics"])

_HEATMAP_TABLE = {
    "hour": "analytics.heatmap_hourly",
    "day": "analytics.heatmap_daily",
    "week": "analytics.heatmap_weekly",
    "month": "analytics.heatmap_monthly",
}


def _parse_ids(raw: str | None) -> list[uuid.UUID]:
    if not raw:
        return []
    return [uuid.UUID(p.strip()) for p in raw.split(",") if p.strip()]


async def _fetch(db: AsyncSession, sql: str, params: dict, id_param: str | None = None):
    """Execute a read query; if id_param is set, bind it as an expanding IN list."""
    stmt = text(sql)
    if id_param:
        stmt = stmt.bindparams(bindparam(id_param, expanding=True))
    result = await db.execute(stmt, params)
    return [dict(r._mapping) for r in result]


@router.get("/store/{slug}/analytics/store-series", response_model=StoreSeriesResponse)
async def store_series(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    granularity: str | None = Query(default="auto"),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    grain = ag.resolve_grain(from_d, to_d, granularity)
    table = ag.STORE_TABLE[grain]
    bs = ag.store_bucket_start(grain)
    where = ag.store_range_filter(grain)

    if grain == "day":
        sql = f"""
            SELECT {bs} AS bucket_start, total_visits, unique_visitors,
                   avg_visit_duration_ms, median_visit_duration_ms, peak_occupancy,
                   peak_occupancy_at_ms, dead_period_count, dead_period_total_ms,
                   TRUE AS is_complete
            FROM {table}
            WHERE store_id = :sid AND {where}
            ORDER BY bucket_start
        """
    else:
        sql = f"""
            SELECT {bs} AS bucket_start, total_visits, unique_visitors,
                   avg_visit_duration_ms, median_visit_duration_ms, peak_occupancy,
                   NULL::BIGINT AS peak_occupancy_at_ms, dead_period_count,
                   NULL::BIGINT AS dead_period_total_ms, is_complete
            FROM {table}
            WHERE store_id = :sid AND {where}
            ORDER BY bucket_start
        """
    rows = await _fetch(db, sql, {"sid": ctx.store_id, "from_d": from_d, "to_d": to_d})
    return StoreSeriesResponse(
        store_id=ctx.store_id, grain=grain, from_=from_d, to=to_d,
        rows=[StoreSeriesRow(**r) for r in rows],
    )


@router.get("/store/{slug}/analytics/zones", response_model=ZonesResponse)
async def zones(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    granularity: str | None = Query(default="auto"),
    zone_ids: str | None = Query(default=None),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    grain = ag.resolve_grain(from_d, to_d, granularity)
    table = ag.ZONE_TABLE[grain]
    params = {"sid": ctx.store_id, "from_d": from_d, "to_d": to_d}
    ids = _parse_ids(zone_ids)
    id_clause = ""
    if ids:
        id_clause = " AND t.zone_id IN :zone_ids"
        params["zone_ids"] = ids

    if grain == "day":
        where = "t.date BETWEEN :from_d AND :to_d"
        sql = f"""
            SELECT t.zone_id, z.name AS zone_name, t.date AS bucket_start,
                   t.unique_visitors, t.total_transitions, t.avg_dwell_ms,
                   t.median_dwell_ms, t.max_concurrent, t.passthrough_count,
                   t.engagement_count, t.alert_trigger_count, TRUE AS is_complete
            FROM {table} t
            JOIN zones z ON z.id = t.zone_id
            WHERE t.store_id = :sid AND {where}{id_clause}
            ORDER BY z.name, bucket_start
        """
    else:
        bs = ag.computed_bucket_start(grain)
        where = ag.computed_range_filter(grain)
        sql = f"""
            SELECT t.zone_id, z.name AS zone_name, {bs} AS bucket_start,
                   t.unique_visitors, NULL::INTEGER AS total_transitions,
                   t.avg_dwell_ms, t.median_dwell_ms, NULL::INTEGER AS max_concurrent,
                   t.passthrough_count, t.engagement_count,
                   NULL::INTEGER AS alert_trigger_count, t.is_complete
            FROM {table} t
            JOIN zones z ON z.id = t.zone_id
            WHERE t.store_id = :sid AND {where}{id_clause}
            ORDER BY z.name, bucket_start
        """
    rows = await _fetch(db, sql, params, id_param="zone_ids" if ids else None)
    return ZonesResponse(
        store_id=ctx.store_id, grain=grain, from_=from_d, to=to_d,
        rows=[ZoneRow(**r) for r in rows],
    )


@router.get("/store/{slug}/analytics/composition", response_model=CompositionResponse)
async def composition(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    granularity: str | None = Query(default="auto"),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    grain = ag.resolve_grain(from_d, to_d, granularity)

    if grain == "day":
        sql = """
            SELECT s.date AS bucket_start, s.unique_visitors AS customers,
                   COALESCE(e.staff, 0) AS staff, TRUE AS is_complete
            FROM analytics.daily_store_summary s
            LEFT JOIN (
                SELECT date, COUNT(DISTINCT employee_id) AS staff
                FROM analytics.daily_employee_summary
                WHERE store_id = :sid AND present_duration_ms > 0
                GROUP BY date
            ) e ON e.date = s.date
            WHERE s.store_id = :sid AND s.date BETWEEN :from_d AND :to_d
            ORDER BY bucket_start
        """
    elif grain == "week":
        sql = """
            SELECT s.week_start_date AS bucket_start, s.unique_visitors AS customers,
                   COALESCE(e.staff, 0) AS staff, s.is_complete
            FROM analytics.weekly_store_summary s
            LEFT JOIN (
                SELECT iso_year, iso_week, COUNT(DISTINCT employee_id) AS staff
                FROM analytics.weekly_employee_summary
                WHERE store_id = :sid AND present_duration_ms > 0
                GROUP BY iso_year, iso_week
            ) e ON e.iso_year = s.iso_year AND e.iso_week = s.iso_week
            WHERE s.store_id = :sid
              AND s.week_start_date <= :to_d
              AND (s.week_start_date + INTERVAL '6 days') >= :from_d
            ORDER BY bucket_start
        """
    else:
        sql = """
            SELECT s.month_start_date AS bucket_start, s.unique_visitors AS customers,
                   COALESCE(e.staff, 0) AS staff, s.is_complete
            FROM analytics.monthly_store_summary s
            LEFT JOIN (
                SELECT year, month, COUNT(DISTINCT employee_id) AS staff
                FROM analytics.monthly_employee_summary
                WHERE store_id = :sid AND present_duration_ms > 0
                GROUP BY year, month
            ) e ON e.year = s.year AND e.month = s.month
            WHERE s.store_id = :sid
              AND s.month_start_date <= :to_d
              AND (s.month_start_date + INTERVAL '1 month') > :from_d
            ORDER BY bucket_start
        """
    rows = await _fetch(db, sql, {"sid": ctx.store_id, "from_d": from_d, "to_d": to_d})
    return CompositionResponse(
        store_id=ctx.store_id, grain=grain, from_=from_d, to=to_d,
        rows=[CompositionRow(**r) for r in rows],
    )


@router.get("/store/{slug}/analytics/distribution", response_model=DistributionResponse)
async def distribution(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    ag.validate_range(from_d, to_d)
    sql = """
        SELECT bucket_label, MIN(bucket_min_ms) AS bucket_min_ms,
               MAX(bucket_max_ms) AS bucket_max_ms, SUM(visit_count) AS visit_count
        FROM analytics.visit_duration_distribution
        WHERE store_id = :sid AND date BETWEEN :from_d AND :to_d
        GROUP BY bucket_label
        ORDER BY MIN(bucket_min_ms)
    """
    rows = await _fetch(db, sql, {"sid": ctx.store_id, "from_d": from_d, "to_d": to_d})
    return DistributionResponse(
        store_id=ctx.store_id, grain="day", from_=from_d, to=to_d,
        rows=[DistributionRow(**r) for r in rows],
    )


@router.get("/store/{slug}/analytics/employees", response_model=EmployeesResponse)
async def employees(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    granularity: str | None = Query(default="auto"),
    employee_ids: str | None = Query(default=None),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    grain = ag.resolve_grain(from_d, to_d, granularity)
    table = ag.EMP_TABLE[grain]
    params = {"sid": ctx.store_id, "from_d": from_d, "to_d": to_d}
    ids = _parse_ids(employee_ids)
    id_clause = ""
    if ids:
        id_clause = " AND t.employee_id IN :employee_ids"
        params["employee_ids"] = ids

    if grain == "day":
        where = "t.date BETWEEN :from_d AND :to_d"
        sql = f"""
            SELECT t.employee_id, em.name AS employee_name, t.date AS bucket_start,
                   t.scheduled_duration_ms, t.present_duration_ms, t.presence_ratio,
                   t.zone_punctuality_delay_ms, t.unassigned_zone_time_ms,
                   TRUE AS is_complete
            FROM {table} t
            JOIN employees em ON em.id = t.employee_id
            WHERE t.store_id = :sid AND {where}{id_clause}
            ORDER BY em.name, bucket_start
        """
    else:
        bs = ag.computed_bucket_start(grain)
        where = ag.computed_range_filter(grain)
        sql = f"""
            SELECT t.employee_id, em.name AS employee_name, {bs} AS bucket_start,
                   t.scheduled_duration_ms, t.present_duration_ms,
                   t.avg_presence_ratio AS presence_ratio,
                   t.avg_punctuality_delay_ms AS zone_punctuality_delay_ms,
                   NULL::BIGINT AS unassigned_zone_time_ms, t.is_complete
            FROM {table} t
            JOIN employees em ON em.id = t.employee_id
            WHERE t.store_id = :sid AND {where}{id_clause}
            ORDER BY em.name, bucket_start
        """
    rows = await _fetch(db, sql, params, id_param="employee_ids" if ids else None)
    return EmployeesResponse(
        store_id=ctx.store_id, grain=grain, from_=from_d, to=to_d,
        rows=[EmployeeRow(**r) for r in rows],
    )


@router.get("/store/{slug}/analytics/flow-matrix", response_model=FlowMatrixResponse)
async def flow_matrix(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    ag.validate_range(from_d, to_d)
    # Sum transition_count per (from,to) across the range, then recompute
    # probability = count / sum(count from each from_zone). NULL zone ids
    # (FK SET NULL) are kept via IS NOT DISTINCT FROM in the per-from join.
    sql = """
        WITH agg AS (
            SELECT from_zone_id, to_zone_id, SUM(transition_count) AS transition_count
            FROM analytics.zone_sequence_matrix
            WHERE store_id = :sid AND date BETWEEN :from_d AND :to_d
            GROUP BY from_zone_id, to_zone_id
        ),
        tot AS (
            SELECT from_zone_id, SUM(transition_count) AS from_total
            FROM agg GROUP BY from_zone_id
        )
        SELECT a.from_zone_id, fz.name AS from_zone_name,
               a.to_zone_id, tz.name AS to_zone_name,
               a.transition_count,
               CASE WHEN t.from_total > 0
                    THEN a.transition_count::float / t.from_total ELSE 0 END AS probability
        FROM agg a
        JOIN tot t ON t.from_zone_id IS NOT DISTINCT FROM a.from_zone_id
        LEFT JOIN zones fz ON fz.id = a.from_zone_id
        LEFT JOIN zones tz ON tz.id = a.to_zone_id
        ORDER BY a.from_zone_id, a.transition_count DESC
    """
    rows = await _fetch(db, sql, {"sid": ctx.store_id, "from_d": from_d, "to_d": to_d})
    return FlowMatrixResponse(
        store_id=ctx.store_id, grain="day", from_=from_d, to=to_d,
        rows=[FlowMatrixRow(**r) for r in rows],
    )


def _local_date_range_to_ms(from_d: date, to_d: date, tz_str: str | None) -> tuple[int, int]:
    """Convert a store-local [from, to] date range to a [start_ms, end_ms) UTC epoch-ms
    window for the hourly heatmap (hour_bucket is UTC epoch ms, like timestamp_ms)."""
    try:
        tz = ZoneInfo(tz_str or "UTC")
    except Exception:
        tz = timezone.utc
    start = datetime(from_d.year, from_d.month, from_d.day, tzinfo=tz)
    end_excl = datetime(to_d.year, to_d.month, to_d.day, tzinfo=tz) + timedelta(days=1)
    to_ms = lambda d: int(d.astimezone(timezone.utc).timestamp() * 1000)
    return to_ms(start), to_ms(end_excl)


@router.get("/store/{slug}/analytics/heatmap", response_model=HeatmapResponse)
async def heatmap(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    granularity: str = Query(default="day"),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    ag.validate_range(from_d, to_d)
    grain = (granularity or "day").lower()
    if grain not in _HEATMAP_TABLE:
        raise HTTPException(
            status_code=422,
            detail={"error": "granularity must be one of hour|day|week|month", "code": "INVALID_GRANULARITY"},
        )

    # Projection always uses the store's ACTIVE version floor plan — that is the
    # frame whose image the overlay is drawn on (E3 known-limitation: historical
    # cells from a prior version reproject in the active frame).
    version_result = await db.execute(
        select(StoreConfigVersion).where(
            StoreConfigVersion.store_id == ctx.store_id,
            StoreConfigVersion.status == "active",
        )
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail={"error": "No active version", "code": "NO_ACTIVE_VERSION"})

    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == version.id,
            FloorPlan.store_id == ctx.store_id,
        )
    )
    fp = fp_result.scalar_one_or_none()

    fp_meta = None
    if fp is not None:
        fp_meta = HeatmapFloorPlan(
            origin_x=fp.origin_x,
            origin_y=fp.origin_y,
            pixels_per_meter=fp.pixels_per_meter,
            world_x_min=fp.world_x_min,
            world_x_max=fp.world_x_max,
            world_y_min=fp.world_y_min,
            world_y_max=fp.world_y_max,
            width_px=fp.width_px,
            height_px=fp.height_px,
            display_url=safe_presign_public(fp.display_s3_key),
            image_uploaded=fp.image_uploaded,
        )

    cell = settings.HEATMAP_CELL_SIZE_M

    # No usable floor plan → metadata + empty cells (never 500).
    if fp is None or not fp.image_uploaded:
        return HeatmapResponse(
            store_id=ctx.store_id, grain=grain, from_=from_d, to=to_d,
            version_id=version.id, cell_size_m=cell, max_hit_count=0,
            floor_plan=fp_meta, cells=[],
        )

    table = _HEATMAP_TABLE[grain]
    params = {"sid": ctx.store_id, "from_d": from_d, "to_d": to_d}
    if grain == "hour":
        from_ms, to_ms = _local_date_range_to_ms(from_d, to_d, ctx.store.timezone)
        where = "hour_bucket >= :from_ms AND hour_bucket < :to_ms"
        params = {"sid": ctx.store_id, "from_ms": from_ms, "to_ms": to_ms}
    elif grain == "day":
        where = "date BETWEEN :from_d AND :to_d"
    else:  # week / month — tables key on iso/year-month, reuse computed filters
        where = ag.computed_range_filter(grain)

    sql = f"""
        SELECT grid_x, grid_y, SUM(hit_count) AS hit_count
        FROM {table}
        WHERE store_id = :sid AND {where}
        GROUP BY grid_x, grid_y
    """
    raw = await _fetch(db, sql, params)

    origin_x = fp.origin_x if fp.origin_x is not None else 0.0
    origin_y = fp.origin_y if fp.origin_y is not None else 0.0
    max_hit = max((r["hit_count"] for r in raw), default=0)

    cells = []
    for r in raw:
        gx, gy, hits = r["grid_x"], r["grid_y"], r["hit_count"]
        wx_min = origin_x + gx * cell
        wy_min = origin_y + gy * cell
        cells.append(
            HeatmapCell(
                grid_x=gx, grid_y=gy, hit_count=hits,
                intensity=(hits / max_hit) if max_hit else 0.0,
                world_x_min=wx_min, world_x_max=wx_min + cell,
                world_y_min=wy_min, world_y_max=wy_min + cell,
            )
        )

    return HeatmapResponse(
        store_id=ctx.store_id, grain=grain, from_=from_d, to=to_d,
        version_id=version.id, cell_size_m=cell, max_hit_count=max_hit,
        floor_plan=fp_meta, cells=cells,
    )
