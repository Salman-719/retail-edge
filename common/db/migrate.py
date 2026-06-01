"""Idempotent schema apply for the IEP2/IEP3 subsystem.

Creates the eight Domain 9 tables (``common/models``) if they don't already
exist -- SQLAlchemy's ``create_all`` is checkfirst, so this is safe to run on a
fresh database OR an existing volume that predates these tables. This is the
repo's stand-in for an Alembic ``upgrade head`` one-shot (the project has no
Alembic); ``services/eep/schema.sql`` only runs on first Postgres init, so this
is what brings an existing volume up to date.

Run standalone or as the compose ``migrate`` one-shot:
    python -m common.db.migrate
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from common.db.engine import dispose_engine, get_engine
from common.models import Base

log = logging.getLogger(__name__)


async def apply_schema() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for column in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"):
            await conn.execute(text(f"ALTER TABLE tracking_history ADD COLUMN IF NOT EXISTS {column} FLOAT"))
    await dispose_engine()


def main() -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] migrate: %(message)s")
    log.info("applying IEP2/IEP3 subsystem schema (create_all, checkfirst)")
    asyncio.run(apply_schema())
    log.info("schema up to date")


if __name__ == "__main__":
    main()
