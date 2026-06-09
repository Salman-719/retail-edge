"""Alerts read & resolve API (D1/D2).

IEP4 writes alerts; this exposes them. Active = resolved_at IS NULL. History =
resolved (filterable, paginated). Manual dismiss = manual_dismiss + resolved_by,
idempotent (never clobbers an existing auto_detected resolution). Generic over
every alert type — no per-type branching.

Reads: any store member. Resolve: owner/manager. Admin via A1 bypass.
NOTE(D3): severity is not selected yet (column added by D3).
"""
import json
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import analytics_grains as ag
from app.core.alert_defaults import RULE_DEFAULTS
from app.core.audit import write_audit_log
from app.core.database import get_db
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.alert_rule import AlertRule, AlertRuleZone
from app.models.employee import Employee
from app.models.version import StoreConfigVersion
from app.models.zone import Zone
from app.schemas.alert import (
    AlertHistoryResponse,
    AlertResponse,
    AlertTimeseriesResponse,
    AlertTimeseriesRow,
)
from app.schemas.alert_rule import (
    RULE_TYPES,
    SEVERITIES,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
    ZoneRef,
)

router = APIRouter(tags=["alerts"])

_BASE_SELECT = """
    SELECT a.id, a.type, a.severity, a.zone_id, z.name AS zone_name,
           a.employee_id, e.name AS employee_name,
           a.details, a.created_at, a.is_followup,
           a.alert_rule_id, r.name AS alert_rule_name,
           a.resolved_at, a.resolution, a.resolved_by, u.name AS resolved_by_name
    FROM alerts a
    LEFT JOIN zones z       ON z.id = a.zone_id
    LEFT JOIN employees e   ON e.id = a.employee_id
    LEFT JOIN alert_rules r ON r.id = a.alert_rule_id
    LEFT JOIN users u       ON u.id = a.resolved_by
"""


def _to_response(row: dict) -> AlertResponse:
    details = row.get("details")
    if isinstance(details, str):  # asyncpg may hand back JSONB as text
        try:
            details = json.loads(details)
        except (ValueError, TypeError):
            details = None
    return AlertResponse(**{**row, "details": details})


async def _fetch_one(db: AsyncSession, store_id, alert_id) -> dict | None:
    result = await db.execute(
        text(_BASE_SELECT + " WHERE a.id = :aid AND a.store_id = :sid"),
        {"aid": alert_id, "sid": store_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


@router.get("/store/{slug}/alerts/active", response_model=list[AlertResponse])
async def active_alerts(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(_BASE_SELECT + " WHERE a.store_id = :sid AND a.resolved_at IS NULL ORDER BY a.created_at DESC"),
        {"sid": ctx.store_id},
    )
    return [_to_response(dict(r)) for r in result.mappings().all()]


@router.get("/store/{slug}/alerts/history", response_model=AlertHistoryResponse)
async def alert_history(
    from_d: date | None = Query(default=None, alias="from"),
    to_d: date | None = Query(default=None, alias="to"),
    type: str | None = Query(default=None),
    resolution: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    # History = resolved alerts, newest first, filterable + paginated.
    clauses = ["a.store_id = :sid", "a.resolved_at IS NOT NULL"]
    params: dict = {"sid": ctx.store_id}
    if from_d is not None:
        clauses.append("a.created_at >= :from_d")
        params["from_d"] = from_d
    if to_d is not None:
        clauses.append("a.created_at < (:to_d::date + 1)")
        params["to_d"] = to_d
    if type is not None:
        clauses.append("a.type = :type")
        params["type"] = type
    if resolution is not None:
        clauses.append("a.resolution = :resolution")
        params["resolution"] = resolution
    where = " WHERE " + " AND ".join(clauses)

    total_res = await db.execute(text("SELECT COUNT(*) FROM alerts a" + where), params)
    total = total_res.scalar_one()

    rows_res = await db.execute(
        text(_BASE_SELECT + where + " ORDER BY a.created_at DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    )
    alerts = [_to_response(dict(r)) for r in rows_res.mappings().all()]
    return AlertHistoryResponse(total=total, limit=limit, offset=offset, alerts=alerts)


_TS_BUCKET = {
    "day": "ld",
    "week": "date_trunc('week', ld)::date",
    "month": "date_trunc('month', ld)::date",
}


@router.get("/store/{slug}/alerts/timeseries", response_model=AlertTimeseriesResponse)
async def alerts_timeseries(
    from_d: date = Query(alias="from"),
    to_d: date = Query(alias="to"),
    granularity: str | None = Query(default="auto"),
    resolution: str | None = Query(default=None),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    # Counts are additive — bucket alerts.created_at (store-local) by the resolved
    # grain, grouped by type + severity. Reuses E1's grain resolver (one source).
    # Declared BEFORE /alerts/{alert_id} so this literal path isn't UUID-captured.
    grain = ag.resolve_grain(from_d, to_d, granularity)
    bucket = _TS_BUCKET[grain]
    params = {"sid": ctx.store_id, "tz": ctx.store.timezone or "UTC", "from_d": from_d, "to_d": to_d}
    res_clause = ""
    if resolution is not None:
        res_clause = " AND resolution = :resolution"
        params["resolution"] = resolution

    sql = f"""
        SELECT {bucket} AS bucket_start, type, severity, COUNT(*) AS count
        FROM (
            SELECT (created_at AT TIME ZONE :tz)::date AS ld, type, severity, resolution
            FROM alerts
            WHERE store_id = :sid
        ) x
        WHERE ld BETWEEN :from_d AND :to_d{res_clause}
        GROUP BY {bucket}, type, severity
        ORDER BY {bucket}, type, severity
    """
    result = await db.execute(text(sql), params)
    rows = [AlertTimeseriesRow(**dict(r)) for r in result.mappings().all()]
    return AlertTimeseriesResponse(
        store_id=ctx.store_id, grain=grain, from_=from_d, to=to_d, rows=rows,
    )


@router.get("/store/{slug}/alerts/{alert_id}", response_model=AlertResponse)
async def alert_detail(
    alert_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    row = await _fetch_one(db, ctx.store_id, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "Alert not found", "code": "NOT_FOUND"})
    return _to_response(row)


@router.post("/store/{slug}/alerts/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    row = await _fetch_one(db, ctx.store_id, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "Alert not found", "code": "NOT_FOUND"})

    # Idempotent: never clobber an existing resolution (auto_detected wins if it fired).
    if row["resolved_at"] is None:
        await db.execute(
            text(
                "UPDATE alerts SET resolved_at = now(), resolution = 'manual_dismiss', "
                "resolved_by = :uid WHERE id = :aid AND store_id = :sid AND resolved_at IS NULL"
            ),
            {"uid": ctx.user_id, "aid": alert_id, "sid": ctx.store_id},
        )
        await write_audit_log(
            db, "alert_dismissed", store_id=ctx.store_id, user_id=ctx.user_id,
            entity_type="alert", entity_id=alert_id,
        )
        await db.commit()
        row = await _fetch_one(db, ctx.store_id, alert_id)

    return _to_response(row)


# ─── D3: Alert rule CRUD ─────────────────────────────────────────────────────

async def _active_version_zone_ids(db: AsyncSession, store_id) -> set:
    res = await db.execute(
        select(Zone.id)
        .join(StoreConfigVersion, StoreConfigVersion.id == Zone.version_id)
        .where(StoreConfigVersion.store_id == store_id, StoreConfigVersion.status == "active")
    )
    return {r[0] for r in res.all()}


def _bad_rule(msg: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": msg, "code": "INVALID_RULE"})


async def _validate_rule(
    db: AsyncSession, store_id, *, type, severity, threshold_minutes, cooldown_minutes,
    followup_interval_minutes, people_threshold, min_employees, employee_id, zone_ids,
) -> None:
    """Mirror the DB CHECKs (so the user gets 422, not a 500) + ownership checks."""
    if type not in RULE_TYPES:
        raise _bad_rule("type must be one of " + ", ".join(sorted(RULE_TYPES)))
    if severity not in SEVERITIES:
        raise _bad_rule("severity must be one of low|medium|high|critical")
    for fld, val in (
        ("threshold_minutes", threshold_minutes),
        ("cooldown_minutes", cooldown_minutes),
        ("followup_interval_minutes", followup_interval_minutes),
    ):
        if val is None or val <= 0:
            raise _bad_rule(f"{fld} must be > 0")
    if cooldown_minutes < threshold_minutes:
        raise _bad_rule("cooldown_minutes must be >= threshold_minutes")

    if type == "queue_buildup":
        if people_threshold is None:
            raise _bad_rule("queue_buildup requires people_threshold")
        if not zone_ids:
            raise _bad_rule("queue_buildup requires at least one zone")
    elif type == "staff_absence_zone":
        if min_employees is None:
            raise _bad_rule("staff_absence_zone requires min_employees")
        if not zone_ids:
            raise _bad_rule("staff_absence_zone requires at least one zone")
    elif type == "staff_absence_employee":
        if employee_id is None:
            raise _bad_rule("staff_absence_employee requires employee_id")
        if zone_ids:
            raise _bad_rule("staff_absence_employee must not have zones")

    if employee_id is not None:
        res = await db.execute(
            select(Employee.id).where(Employee.id == employee_id, Employee.store_id == store_id)
        )
        if res.scalar_one_or_none() is None:
            raise _bad_rule("employee_id does not belong to this store")

    if zone_ids:
        active = await _active_version_zone_ids(db, store_id)
        missing = [str(z) for z in zone_ids if z not in active]
        if missing:
            raise _bad_rule("zones not in the active version: " + ", ".join(missing))


def _rule_snapshot(rule: AlertRule) -> dict:
    return {
        "type": rule.type, "name": rule.name, "severity": rule.severity, "is_active": rule.is_active,
        "threshold_minutes": rule.threshold_minutes, "cooldown_minutes": rule.cooldown_minutes,
        "followup_interval_minutes": rule.followup_interval_minutes,
        "only_during_shift": rule.only_during_shift,
        "people_threshold": rule.people_threshold, "min_employees": rule.min_employees,
        "employee_id": str(rule.employee_id) if rule.employee_id else None,
        "zone_ids": [str(z.zone_id) for z in rule.zones],
    }


async def _zone_names(db: AsyncSession, zone_ids: list) -> dict:
    if not zone_ids:
        return {}
    res = await db.execute(select(Zone.id, Zone.name).where(Zone.id.in_(zone_ids)))
    return {r.id: r.name for r in res.all()}


async def _employee_names(db: AsyncSession, emp_ids: list) -> dict:
    ids = [e for e in emp_ids if e]
    if not ids:
        return {}
    res = await db.execute(select(Employee.id, Employee.name).where(Employee.id.in_(ids)))
    return {r.id: r.name for r in res.all()}


def _rule_response(rule: AlertRule, zone_names: dict, emp_names: dict) -> AlertRuleResponse:
    zids = [z.zone_id for z in rule.zones]
    return AlertRuleResponse(
        id=rule.id, type=rule.type, name=rule.name, severity=rule.severity,
        is_active=rule.is_active, threshold_minutes=rule.threshold_minutes,
        cooldown_minutes=rule.cooldown_minutes,
        followup_interval_minutes=rule.followup_interval_minutes,
        only_during_shift=rule.only_during_shift, people_threshold=rule.people_threshold,
        min_employees=rule.min_employees, employee_id=rule.employee_id,
        employee_name=emp_names.get(rule.employee_id),
        zones=[ZoneRef(id=zid, name=zone_names.get(zid, "")) for zid in zids],
        created_at=rule.created_at, updated_at=rule.updated_at,
    )


async def _single_rule_response(db: AsyncSession, rule: AlertRule) -> AlertRuleResponse:
    zone_names = await _zone_names(db, [z.zone_id for z in rule.zones])
    emp_names = await _employee_names(db, [rule.employee_id])
    return _rule_response(rule, zone_names, emp_names)


async def _get_rule_or_404(db: AsyncSession, store_id, rule_id) -> AlertRule:
    res = await db.execute(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.store_id == store_id)
    )
    rule = res.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail={"error": "Alert rule not found", "code": "NOT_FOUND"})
    return rule


@router.get("/store/{slug}/alert-rules", response_model=list[AlertRuleResponse])
async def list_alert_rules(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(AlertRule).where(AlertRule.store_id == ctx.store_id).order_by(AlertRule.created_at)
    )
    rules = res.scalars().all()
    zone_names = await _zone_names(db, [z.zone_id for r in rules for z in r.zones])
    emp_names = await _employee_names(db, [r.employee_id for r in rules])
    return [_rule_response(r, zone_names, emp_names) for r in rules]


@router.get("/store/{slug}/alert-rules/defaults")
async def alert_rule_defaults(
    ctx: StoreContext = Depends(get_store_context),
):
    # Create-form defaults (D5). Static constants — registered BEFORE /{rule_id}
    # so this literal path is not captured by the UUID route.
    return RULE_DEFAULTS


@router.post("/store/{slug}/alert-rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    body: AlertRuleCreate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _validate_rule(
        db, ctx.store_id, type=body.type, severity=body.severity,
        threshold_minutes=body.threshold_minutes, cooldown_minutes=body.cooldown_minutes,
        followup_interval_minutes=body.followup_interval_minutes,
        people_threshold=body.people_threshold, min_employees=body.min_employees,
        employee_id=body.employee_id, zone_ids=body.zone_ids,
    )
    rule = AlertRule(
        store_id=ctx.store_id, type=body.type, name=body.name, severity=body.severity,
        is_active=body.is_active, threshold_minutes=body.threshold_minutes,
        cooldown_minutes=body.cooldown_minutes,
        followup_interval_minutes=body.followup_interval_minutes,
        people_threshold=body.people_threshold, min_employees=body.min_employees,
        employee_id=body.employee_id, only_during_shift=body.only_during_shift,
    )
    rule.zones = [AlertRuleZone(zone_id=z) for z in body.zone_ids]
    db.add(rule)
    await db.flush()
    await write_audit_log(
        db, "alert_rule_created", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="alert_rule", entity_id=rule.id, after_state=_rule_snapshot(rule),
    )
    await db.commit()
    return await _single_rule_response(db, rule)


@router.get("/store/{slug}/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    rule_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    rule = await _get_rule_or_404(db, ctx.store_id, rule_id)
    return await _single_rule_response(db, rule)


@router.patch("/store/{slug}/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    rule = await _get_rule_or_404(db, ctx.store_id, rule_id)
    before = _rule_snapshot(rule)

    # Effective merged state (None = unchanged; zone_ids=[] clears).
    pick = lambda new, cur: cur if new is None else new
    eff_employee_id = pick(body.employee_id, rule.employee_id)
    eff_zone_ids = [z.zone_id for z in rule.zones] if body.zone_ids is None else body.zone_ids
    eff = dict(
        type=rule.type,  # type is immutable here
        severity=pick(body.severity, rule.severity),
        threshold_minutes=pick(body.threshold_minutes, rule.threshold_minutes),
        cooldown_minutes=pick(body.cooldown_minutes, rule.cooldown_minutes),
        followup_interval_minutes=pick(body.followup_interval_minutes, rule.followup_interval_minutes),
        people_threshold=pick(body.people_threshold, rule.people_threshold),
        min_employees=pick(body.min_employees, rule.min_employees),
        employee_id=eff_employee_id, zone_ids=eff_zone_ids,
    )
    await _validate_rule(db, ctx.store_id, **eff)

    if body.name is not None:
        rule.name = body.name
    if body.is_active is not None:
        rule.is_active = body.is_active
    if body.only_during_shift is not None:
        rule.only_during_shift = body.only_during_shift
    rule.severity = eff["severity"]
    rule.threshold_minutes = eff["threshold_minutes"]
    rule.cooldown_minutes = eff["cooldown_minutes"]
    rule.followup_interval_minutes = eff["followup_interval_minutes"]
    rule.people_threshold = eff["people_threshold"]
    rule.min_employees = eff["min_employees"]
    rule.employee_id = eff_employee_id
    if body.zone_ids is not None:
        rule.zones = [AlertRuleZone(zone_id=z) for z in body.zone_ids]
    rule.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await write_audit_log(
        db, "alert_rule_updated", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="alert_rule", entity_id=rule.id,
        before_state=before, after_state=_rule_snapshot(rule),
    )
    await db.commit()
    return await _single_rule_response(db, rule)


@router.delete("/store/{slug}/alert-rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    rule = await _get_rule_or_404(db, ctx.store_id, rule_id)
    before = _rule_snapshot(rule)
    await db.delete(rule)
    await write_audit_log(
        db, "alert_rule_deleted", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="alert_rule", entity_id=rule_id, before_state=before,
    )
    await db.commit()
