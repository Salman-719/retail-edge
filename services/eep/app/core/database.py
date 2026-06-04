from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL_EEP,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    # PgBouncer transaction mode: disable asyncpg prepared-statement cache.
    # Without this, asyncpg caches prepared statements per logical connection;
    # PgBouncer may hand the same server connection to a different client whose
    # cache state differs, causing DuplicatePreparedStatementError.
    connect_args={"prepared_statement_cache_size": 0},
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
