import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Add deactivated_at column if it doesn't exist (safe for existing DBs)
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
    await start_grpc_server()
    start_scheduler()
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
