import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete, text

from app.api import register_routers
from app.core.database import AsyncSessionLocal, engine
from app.core import iep2_docker, orchestrator
from app.core.scheduler import start_scheduler, stop_scheduler
from app.grpc_server.server import start_grpc_server, stop_grpc_server
import app.models  # noqa: F401 — registers all SQLAlchemy mappers at startup
from app.models.user import User

logger = logging.getLogger(__name__)


async def _recover_crashed_sessions() -> None:
    """On EEP startup, find open camera_runtime_sessions and attempt to restart IEP2.

    Cameras whose IEP2 container died while EEP was down have an open (stopped_at IS NULL)
    session row. Re-launch IEP2 and re-adopt the existing row so the normal stop path
    closes it cleanly. If restart fails, mark the row 'crash' so history stays complete.
    """
    from app.tasks.camera_scheduler import mark_running

    try:
        async with AsyncSessionLocal() as db:
            rows_result = await db.execute(
                text("""
                    SELECT store_id, physical_camera_id, camera_config_id, version_id, id
                    FROM camera_runtime_sessions
                    WHERE stopped_at IS NULL
                      AND physical_camera_id IS NOT NULL
                      AND camera_config_id   IS NOT NULL
                """)
            )
            sessions = rows_result.fetchall()
    except Exception:
        logger.exception("Crash recovery: DB query failed, skipping")
        return

    loop = asyncio.get_running_loop()
    for row in sessions:
        store_id, physical_camera_id, camera_config_id, version_id, session_id = row
        try:
            from app.core.config import settings as _cfg
            await loop.run_in_executor(
                None,
                iep2_docker.start_iep2,
                str(store_id),
                str(physical_camera_id),
                str(camera_config_id),
                orchestrator._DATABASE_URL_SERVER,
                orchestrator._REDIS_URL,
                orchestrator._S3_ENDPOINT_URL,
                orchestrator._S3_ACCESS_KEY,
                orchestrator._S3_SECRET_KEY,
                orchestrator._S3_BUCKET,
                _cfg.WINDOW_SECONDS,
            )
            # Re-adopt the existing open row so the normal stop path closes it.
            orchestrator._open_sessions[(str(store_id), str(physical_camera_id))] = session_id
            mark_running(str(store_id), str(camera_config_id))
            logger.info(
                "Crash recovery: restarted IEP2 for camera %s", physical_camera_id
            )
        except Exception as exc:
            logger.warning(
                "Crash recovery: failed to restart IEP2 for camera %s: %s",
                physical_camera_id, exc,
            )
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("""
                        UPDATE camera_runtime_sessions
                        SET stopped_at = now(), stop_reason = 'crash'
                        WHERE id = :id
                    """),
                    {"id": session_id},
                )
                await db.commit()


async def _cleanup_deactivated_users():
    while True:
        await asyncio.sleep(86400)  # run once per day
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(User).where(
                        User.deactivated_at.is_not(None),
                        User.deactivated_at <= cutoff,
                    )
                )
                await db.commit()
        except Exception:
            pass


def _run_migrations() -> None:
    """Run Alembic migrations synchronously. Called via run_in_executor."""
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Step 1: run schema migrations before accepting any traffic.
    # Uses a thread executor because Alembic + psycopg2 are synchronous.
    from app.core.config import settings as _settings
    logger.info(
        "EEP starting  window_seconds=%.1f  db_host=%s  debug_mode=%s",
        _settings.WINDOW_SECONDS,
        _settings.DATABASE_URL_EEP.split("@")[-1].split("/")[0],
        _settings.DEBUG_MODE,
    )

    await asyncio.get_running_loop().run_in_executor(None, _run_migrations)

    # Step 2: ORM safety net — ensures tables created by SQLAlchemy models
    # but not yet covered by a migration exist on fresh deployments.
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ"
        ))
        # Phase 4 tables — created via ORM metadata if absent
        import app.models  # noqa: F401 — ensures all mappers are registered
        from app.models.base import Base as ModelBase
        await conn.run_sync(ModelBase.metadata.create_all)

    try:
        from app.core.s3_client import ensure_bucket
        ensure_bucket()
    except Exception:
        pass

    asyncio.create_task(_cleanup_deactivated_users())
    await _recover_crashed_sessions()
    await start_grpc_server()
    start_scheduler()
    from app.tasks.camera_scheduler import rebuild_running_cameras
    await rebuild_running_cameras()
    try:
        yield
    finally:
        stop_scheduler()
        await stop_grpc_server()


app = FastAPI(title="RetailVision EEP", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": str(exc.errors()), "code": "VALIDATION_ERROR"},
    )


register_routers(app)


@app.get("/health")
async def health():
    return {"service": "eep", "status": "ok"}
