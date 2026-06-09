from fastapi import Depends, FastAPI

from app.core.auth import require_super_admin
from app.api.routers.auth import router as auth_router
from app.api.routers.auth import store_auth_router
from app.api.routers.stores import router as stores_router
from app.api.routers.members import router as members_router
from app.api.routers.config import router as config_router
from app.api.routers.draft import router as draft_router
from app.api.routers.employees import router as employees_router
from app.api.routers.shifts import router as shifts_router
from app.api.routers.audit import router as audit_router
from app.api.routers.settings import router as settings_router
from app.api.routers.schedules import router as schedules_router
from app.api.routers.punch import router as punch_router


def register_routers(app: FastAPI) -> None:
    app.include_router(auth_router, prefix="/api")
    app.include_router(store_auth_router, prefix="/api")
    app.include_router(stores_router, prefix="/api")
    app.include_router(members_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(draft_router, prefix="/api")
    app.include_router(employees_router, prefix="/api")
    app.include_router(shifts_router, prefix="/api")
    app.include_router(audit_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(schedules_router, prefix="/api")
    app.include_router(punch_router, prefix="/api")

    # Dev/debug routers: always mounted (incl. production), gated at the router level
    # by super-admin — or any authed user when DEBUG_MODE is on (A4). Prefixes live on
    # the routers themselves (/api/debug, /api/debug/dev), so they are unchanged.
    from app.api.routers.debug import router as debug_router
    from app.api.routers.dev_pipeline import router as dev_pipeline_router
    app.include_router(debug_router, dependencies=[Depends(require_super_admin)])
    app.include_router(dev_pipeline_router, dependencies=[Depends(require_super_admin)])
