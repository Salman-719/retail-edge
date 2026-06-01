from fastapi import FastAPI

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
from app.api.routers.vision import router as vision_router
from app.api.routers.internal import router as internal_router


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
    app.include_router(vision_router, prefix="/api")
    app.include_router(internal_router)  # no /api prefix — internal only
