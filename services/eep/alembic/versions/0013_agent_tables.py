"""IEP6 agent tables: stored insight reports and AI-detected alerts.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-07

Kept separate from `alerts` (whose `type` is a fixed CHECK enum) so the agent can
emit arbitrary insight/anomaly types. Idempotent (IF NOT EXISTS) — also present in
schema.sql so a fresh initdb seed already has them.

Renumbered from 0006 -> 0013 when the reconfig-edge analytics migrations
(0006_camera_intrinsics_pnp .. 0012_crs_stop_reason_eep_restart) were integrated,
so the agent tables apply on top of the analytics/alerts foundation.
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_insights (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id    UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            kind        VARCHAR(40) NOT NULL DEFAULT 'daily_summary',
            title       TEXT NOT NULL,
            body        TEXT NOT NULL,
            metrics     JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_agent_insights_store_ts
            ON agent_insights(store_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS agent_alerts (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id     UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            kind         VARCHAR(40) NOT NULL,
            severity     VARCHAR(10) NOT NULL DEFAULT 'info'
                         CHECK (severity IN ('info', 'warning', 'critical')),
            message      TEXT NOT NULL,
            details      JSONB,
            resolved_at  TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_agent_alerts_store_ts
            ON agent_alerts(store_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_alerts; DROP TABLE IF EXISTS agent_insights;")
