"""Register all EEP routers onto the FastAPI app."""
from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    from app.api import stores, floor_plans, zones, cameras, videos, calibration, tracking, employees

    app.include_router(stores.router,      prefix="/api/stores", tags=["stores"])
    app.include_router(floor_plans.router, prefix="/api/stores", tags=["floor-plans"])
    app.include_router(zones.router,       prefix="/api/stores", tags=["zones"])
    app.include_router(cameras.router,     prefix="/api/stores", tags=["cameras"])
    app.include_router(videos.router,      prefix="/api/stores", tags=["videos"])
    app.include_router(calibration.router, prefix="/api/stores", tags=["calibration"])
    app.include_router(tracking.router,    prefix="/api/stores", tags=["tracking"])
    app.include_router(employees.router,   prefix="/api/stores", tags=["employees"])
