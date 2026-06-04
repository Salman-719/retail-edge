"""PgBouncer compatibility — no DB-level changes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-04

Spec M1-S1 lists this migration in the Architecture Map but does not define
its content. It is a placeholder that reserves the revision slot.

If future DB-level PgBouncer compatibility work is needed (e.g. dropping
prepared-statement caches, resetting pg_stat_statements, or patching session
parameters), add the SQL here and remove this comment.

The code-level PgBouncer changes (statement_cache_size=0 on all asyncpg pools,
prepared_statement_cache_size=0 on the SQLAlchemy engine) are applied in:
  services/eep/app/core/database.py
  services/iep2_vision/persistence/postgres.py
  services/iep3_reconciliation/app/db.py
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
