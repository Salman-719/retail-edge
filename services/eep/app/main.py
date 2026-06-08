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
from app.core.scheduler import start_scheduler, stop_scheduler
from app.grpc_server.server import start_grpc_server, stop_grpc_server
import app.models  # noqa: F401 — registers all SQLAlchemy mappers at startup
from app.models.user import User

logger = logging.getLogger(__name__)


async def _close_orphan_sessions() -> None:
    """Close camera_runtime_sessions that were still open when EEP last crashed.

    In the k3s model, IEP2 crash recovery is k3s's responsibility. EEP only
    needs to close the audit rows so history stays clean. Cameras that should
    still be running will be restarted by the scheduler on the next tick.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("UPDATE camera_runtime_sessions SET stopped_at = now(), stop_reason = 'eep_restart' WHERE stopped_at IS NULL")
            )
            await db.commit()
            if result.rowcount:
                logger.info("Closed %d orphan camera_runtime_sessions", result.rowcount)
    except Exception:
        logger.exception("_close_orphan_sessions: DB update failed, skipping")


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
    _app = app  # local alias — `import app.models` below rebinds the name `app` to the package
    from app.core.config import settings as _settings
    logger.info(
        "EEP starting  window_seconds=%.1f  db_host=%s  debug_mode=%s",
        _settings.WINDOW_SECONDS,
        _settings.DATABASE_URL_EEP.split("@")[-1].split("/")[0],
        _settings.DEBUG_MODE,
    )

    # Step 1: run schema migrations before any other activity.
    await asyncio.get_running_loop().run_in_executor(None, _run_migrations)

    # Step 2: ORM safety net — creates tables not yet covered by migrations.
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ"
        ))
        import app.models  # noqa: F401 — ensures all mappers are registered
        from app.models.base import Base as ModelBase
        await conn.run_sync(ModelBase.metadata.create_all)

    # Step 3: rebuild _running_cameras from Redis before serving any traffic.
    from app.grpc_server.camera_status import rebuild_running_cameras_on_startup
    await rebuild_running_cameras_on_startup()

    # Step 4: rebuild scheduler's _running_cameras from camera_status (Redis-backed).
    from app.tasks.camera_scheduler import rebuild_running_cameras
    await rebuild_running_cameras()

    # Step 5: start gRPC server (Edge Agents may connect now).
    await start_grpc_server()

    # Step 6: start schedule evaluator.
    start_scheduler()

    # Step 7: initialise k8s/Docker clients for IEP3/IEP4/IEP5 provisioning.
    # Gracefully fall back to Docker (production-local) or no-op on the laptop.
    from app.core import iep3_manager, iep4_manager, iep5_manager
    _loop = asyncio.get_running_loop()
    await _loop.run_in_executor(None, iep3_manager.init_k8s_clients)
    await _loop.run_in_executor(None, iep4_manager.init_k8s_clients)
    await _loop.run_in_executor(None, iep5_manager.init_k8s_clients)

    # Non-blocking background tasks — failures here do not block startup.
    try:
        from app.core.s3_client import ensure_bucket
        ensure_bucket()
    except Exception:
        pass

    # Keep strong references to long-lived background tasks. asyncio only holds a
    # weak reference to tasks, so an unreferenced create_task() result can be GC'd
    # before it runs (the resolver's startup log never fired without this).
    from app.core import punch_resolver
    _app.state.background_tasks = [
        asyncio.create_task(_cleanup_deactivated_users()),
        asyncio.create_task(punch_resolver.run_forever()),  # employee-linking
    ]

    await _close_orphan_sessions()

    try:
        yield
    finally:
        stop_scheduler()
        await stop_grpc_server()
        await engine.dispose()


app = FastAPI(title="RetailVision EEP", lifespan=lifespan)

# Prometheus metrics: exposes GET /metrics with request count, latency histogram,
# and error rate. Scraped by Prometheus (job "eep") — see monitoring/prometheus.yml.
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

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
