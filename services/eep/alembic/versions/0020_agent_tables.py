"""IEP6 agent tables: stored insight reports and AI-detected alerts.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-09

Restores the IEP6 agent tables onto the robustness-qa migration chain. They were
on deploy/aws-eks as 0013_agent_tables (down_revision 0012) but were not part of
the robustness-qa sequence (0013_embedding_store .. 0019_recon_trace); re-added
here on top of 0019 so IEP6's stored insights + proactive alerts keep working.

Kept separate from `alerts` (whose `type` is a fixed CHECK enum) so the agent can
emit arbitrary insight/anomaly types. Idempotent (IF NOT EXISTS).

NOTE: IEP6's queue threshold no longer reads alert_configs (retired by
0018_drop_alert_configs); it now reads alert_rules.people_threshold for active
queue_buildup rules — see services/iep6_agent/app/agent/insights.py.
"""
from alembic import op

revision = "0020"
down_revision = "0019"
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
