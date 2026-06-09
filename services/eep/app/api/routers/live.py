"""Live overview API (F1) — one cheap snapshot of the reconciled active set (~60s).

Reads global_identities (state='active'), the live zone from active_person_state, and
employee names. Positions are world metres; the frontend projects. Read-only.
NEVER reads global_tracking_history per-frame — this is the ~60s reconciled set.
"""
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.grpc_server import camera_status as _camera_status
from app.middleware.store_auth import StoreContext, get_store_context
from app.models.edge_agent import EdgeAgent
from app.models.physical_camera import PhysicalCamera
from app.schemas.live import (
    AgentHealth,
    CameraHealth,
    CameraHealthItem,
    LiveKpis,
    LiveOverview,
    LivePerson,
)

router = APIRouter(tags=["live"])

# Edge-agent heartbeat freshness window for "online".
_AGENT_FRESH_S = 90

# Present persons (active + fresh), with their live zone + employee name. The
# (store_id, state) index makes the active scan cheap.
_PRESENT_SQL = text("""
    SELECT gi.global_id, gi.is_employee, gi.last_floor_x, gi.last_floor_y, gi.first_seen_ts,
           aps.current_zone_id, z.name AS current_zone_name, e.name AS employee_name
    FROM global_identities gi
    LEFT JOIN active_person_state aps
           ON aps.global_id = gi.global_id AND aps.store_id = gi.store_id
    LEFT JOIN zones z     ON z.id = aps.current_zone_id
    LEFT JOIN employees e ON e.id = gi.employee_id
    WHERE gi.store_id = :sid AND gi.state = 'active' AND gi.last_seen_ts >= :cutoff
""")


@router.get("/store/{slug}/live/overview", response_model=LiveOverview)
async def live_overview(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - settings.LIVE_STALE_MS

    res = await db.execute(_PRESENT_SQL, {"sid": ctx.store_id, "cutoff": cutoff})
    rows = [dict(r._mapping) for r in res.mappings().all()]

    # KPIs over the SAME present set the dots come from (incl. unplaceable persons).
    total = len(rows)
    staff = sum(1 for r in rows if r["is_employee"])
    customers = total - staff

    alert_res = await db.execute(
        text("SELECT COUNT(*) FROM alerts WHERE store_id = :sid AND resolved_at IS NULL"),
        {"sid": ctx.store_id},
    )
    active_alerts = alert_res.scalar_one()

    # Persons list: only those with a floor fix (count the rest in KPIs, omit here).
    persons = [
        LivePerson(
            global_id=r["global_id"],
            type="staff" if r["is_employee"] else "customer",
            world_x=r["last_floor_x"],
            world_y=r["last_floor_y"],
            current_zone_id=r["current_zone_id"],
            current_zone_name=r["current_zone_name"],
            employee_name=r["employee_name"] if r["is_employee"] else None,
            dwell_ms=now_ms - r["first_seen_ts"],
        )
        for r in rows
        if r["last_floor_x"] is not None and r["last_floor_y"] is not None
    ]

    return LiveOverview(
        generated_at_ms=now_ms,
        kpis=LiveKpis(
            total_people=total, customers=customers,
            staff_on_floor=staff, active_alerts=active_alerts,
        ),
        persons=persons,
    )


@router.get("/store/{slug}/cameras/health", response_model=CameraHealth)
async def cameras_health(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    now_ms = int(time.time() * 1000)

    # All configured cameras, left-joined to the live in-memory status. A camera
    # that never reported still appears as 'unknown' (don't hide gaps).
    cam_res = await db.execute(
        select(PhysicalCamera.id, PhysicalCamera.name)
        .where(PhysicalCamera.store_id == ctx.store_id, PhysicalCamera.is_active == True)  # noqa: E712
        .order_by(PhysicalCamera.created_at)
    )
    statuses = _camera_status.get_for_store(str(ctx.store_id))
    cameras = []
    for cam in cam_res.all():
        st = statuses.get(str(cam.id))
        status = st["status"] if st else "unknown"
        cameras.append(
            CameraHealthItem(
                physical_camera_id=cam.id,
                name=cam.name,
                status=status,
                last_status_ms=st["timestamp_ms"] if st else None,
                online=(status == "running"),
            )
        )

    # Device/agent health from edge_agents (live state, not runtime sessions).
    agent_res = await db.execute(select(EdgeAgent).where(EdgeAgent.store_id == ctx.store_id))
    agent = agent_res.scalar_one_or_none()
    if agent is None:
        agent_block = AgentHealth(online=False)
    else:
        age = None
        online = False
        if agent.last_heartbeat_at is not None:
            age = (datetime.now(timezone.utc) - agent.last_heartbeat_at).total_seconds()
            online = age <= _AGENT_FRESH_S
        agent_block = AgentHealth(
            status=agent.status,
            last_heartbeat_at=agent.last_heartbeat_at,
            heartbeat_age_seconds=age,
            agent_version=agent.agent_version,
            online=online,
        )

    return CameraHealth(cameras=cameras, agent=agent_block, generated_at_ms=now_ms)
