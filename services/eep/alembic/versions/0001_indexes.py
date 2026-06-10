"""Add missing indexes.

Revision ID: 0001
Revises:
Create Date: 2026-06-04

All operations use CREATE/DROP INDEX CONCURRENTLY and run under AUTOCOMMIT
(set in env.py) so they never execute inside a transaction block — a PostgreSQL
requirement for CONCURRENTLY.

Deviation from schema.sql:
  idx_global_identities_store_state  — schema.sql created this WITHOUT the
    partial predicate. We drop it and recreate with WHERE state IN ('active','lost').
  idx_glm_local_id  — same situation; recreated with WHERE is_active = TRUE.
  idx_tracking_history_store_ts  — already exists with identical definition;
    IF NOT EXISTS makes this a no-op on fresh DBs.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SPEC-000: TimescaleDB extension bootstrap. Must run before any spec that
    # creates hypertables. IF NOT EXISTS keeps this idempotent across replays.
    # CASCADE pulls in any required dependencies. Runs first so it precedes the
    # CONCURRENTLY index ops below; safe under AUTOCOMMIT (each statement is its
    # own transaction, satisfying TimescaleDB's "first statement" guidance).
    # The image sets shared_preload_libraries; retailvision is a bootstrap
    # superuser, so no privilege escalation is needed.
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

    # Drop non-partial versions that schema.sql may have created.
    # CONCURRENTLY + IF EXISTS is safe under AUTOCOMMIT.
    op.execute(sa.text(
        "DROP INDEX CONCURRENTLY IF EXISTS idx_global_identities_store_state"
    ))
    op.execute(sa.text(
        "DROP INDEX CONCURRENTLY IF EXISTS idx_glm_local_id"
    ))

    # idx_tracking_history_store_ts — already correct in schema.sql; IF NOT EXISTS skips.
    op.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tracking_history_store_ts "
        "ON tracking_history(store_id, timestamp_ms)"
    ))

    # Partial index: only index active/lost rows — reduces size ~50% once exits accumulate.
    op.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_global_identities_store_state "
        "ON global_identities(store_id, state) "
        "WHERE state IN ('active', 'lost')"
    ))

    # Partial index: only active links — the hot path for reconciliation lookups.
    op.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_glm_local_id "
        "ON global_local_mapping(local_id) "
        "WHERE is_active = TRUE"
    ))

    op.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_edge_agents_status "
        "ON edge_agents(status)"
    ))

    op.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_gth_global_batch "
        "ON global_tracking_history(global_id, batch_number)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS idx_tracking_history_store_ts"))
    op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS idx_global_identities_store_state"))
    op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS idx_glm_local_id"))
    op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS idx_edge_agents_status"))
    op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS idx_gth_global_batch"))

    # Restore the original non-partial versions that schema.sql expects.
    op.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_global_identities_store_state "
        "ON global_identities(store_id, state)"
    ))
    op.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_glm_local_id "
        "ON global_local_mapping(local_id)"
    ))
