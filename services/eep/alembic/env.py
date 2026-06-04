"""Alembic migration environment.

Uses psycopg2 (sync) with AUTOCOMMIT isolation so that CREATE/DROP INDEX
CONCURRENTLY works correctly — those statements cannot run inside a transaction.
All migrations must be idempotent (IF EXISTS / IF NOT EXISTS) because they run
under AUTOCOMMIT where partial failure leaves state as-is.

Connection URL resolution (in priority order):
  1. ALEMBIC_DATABASE_URL env var  — direct psycopg2 URL, bypasses PgBouncer
  2. DATABASE_URL env var           — asyncpg URL rewritten to psycopg2 + postgres host
"""
import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL", "")
    if url:
        return url
    # Fall back: rewrite async URL to sync psycopg2, route around PgBouncer
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
    url = url.replace("+asyncpg", "+psycopg2")
    url = url.replace("@pgbouncer:", "@postgres:")
    return url


config.set_main_option("sqlalchemy.url", _resolve_url())

# No autogenerate — we manage all DDL by hand.
target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = sa.create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
        # AUTOCOMMIT: required for CREATE/DROP INDEX CONCURRENTLY which must
        # not run inside a transaction block.
        isolation_level="AUTOCOMMIT",
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=False,
        )
        # No begin_transaction wrapper — AUTOCOMMIT engine handles commits.
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
