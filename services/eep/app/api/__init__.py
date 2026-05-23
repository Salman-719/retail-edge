from fastapi import FastAPI

from app.api.routers.auth import router as auth_router
from app.api.routers.auth import store_auth_router
from app.api.routers.stores import router as stores_router
from app.api.routers.members import router as members_router
from app.api.routers.config import router as config_router
from app.api.routers.draft import router as draft_router


def register_routers(app: FastAPI) -> None:
    app.include_router(auth_router, prefix="/api")
    app.include_router(store_auth_router, prefix="/api")
    app.include_router(stores_router, prefix="/api")
    app.include_router(members_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(draft_router, prefix="/api")
