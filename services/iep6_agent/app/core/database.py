"""Read-only async DB access for the agent's analytics tools."""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL_AGENT,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    # PgBouncer transaction-mode safety (same as EEP).
    connect_args={
        "prepared_statement_cache_size": 0,
        # Hard cap any query the agent issues (cost/runaway guard).
        "server_settings": {"statement_timeout": str(settings.SQL_STATEMENT_TIMEOUT_MS)},
    },
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
