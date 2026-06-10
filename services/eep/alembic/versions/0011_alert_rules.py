"""Alert rules, rule-zones, alert state, and alerts columns (SPEC-003, Part A).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-08

Schema for the IEP4 alert-evaluation daemon: configurable per-zone alert rules
(alert_rules), the many-to-many zones per rule (alert_rule_zones), IEP4's
runtime cooldown state machine (alert_state), and two columns on the existing
alerts table (alert_rule_id, is_followup). alert_configs is left untouched for
backward compatibility.

Deviation from the SPEC-003 draft: the draft said "add to migration 0004".
0004 is taken (batch_number_bigint) and SPEC-001's analytics migration landed
as 0010, already applied. Adding to an applied migration is a no-op, so this is
a new migration 0011 chained off 0010. Idempotent (IF NOT EXISTS) and runs on
both fresh-init and existing DBs, so the two paths converge.

Runs under AUTOCOMMIT (env.py) directly against postgres:5432.
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. alert_rules ───────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_rules (
            id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                  UUID         NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            type                      VARCHAR(30)  NOT NULL
                                      CHECK (type IN (
                                          'queue_buildup',
                                          'staff_absence_zone',
                                          'staff_absence_employee'
                                      )),
            name                      VARCHAR(255) NOT NULL,
            is_active                 BOOLEAN      NOT NULL DEFAULT TRUE,
            threshold_minutes         INTEGER      NOT NULL,
            cooldown_minutes          INTEGER      NOT NULL DEFAULT 30,
            followup_interval_minutes INTEGER      NOT NULL DEFAULT 5,
            people_threshold          INTEGER,
            min_employees             INTEGER,
            employee_id               UUID         REFERENCES employees(id) ON DELETE CASCADE,
            only_during_shift         BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT queue_buildup_requires_people
                CHECK (type != 'queue_buildup' OR people_threshold IS NOT NULL),
            CONSTRAINT staff_absence_zone_requires_min_employees
                CHECK (type != 'staff_absence_zone' OR min_employees IS NOT NULL),
            CONSTRAINT staff_absence_employee_requires_employee
                CHECK (type != 'staff_absence_employee' OR employee_id IS NOT NULL),
            CONSTRAINT cooldown_gte_threshold
                CHECK (cooldown_minutes >= threshold_minutes)
        );

        CREATE INDEX IF NOT EXISTS idx_alert_rules_store
            ON alert_rules(store_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_alert_rules_employee
            ON alert_rules(employee_id)
            WHERE employee_id IS NOT NULL;
        """
    )

    # ── 2. alert_rule_zones ──────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_rule_zones (
            alert_rule_id UUID NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
            zone_id       UUID NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
            PRIMARY KEY (alert_rule_id, zone_id)
        );

        CREATE INDEX IF NOT EXISTS idx_arz_zone
            ON alert_rule_zones(zone_id);
        """
    )

    # ── 3. alert_state — IEP4 cooldown state machine ─────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_state (
            alert_rule_id          UUID        PRIMARY KEY
                                   REFERENCES alert_rules(id) ON DELETE CASCADE,
            status                 VARCHAR(20) NOT NULL DEFAULT 'idle'
                                   CHECK (status IN ('idle', 'firing', 'cooldown')),
            condition_first_met_at BIGINT,
            fired_at               BIGINT,
            condition_cleared_at   BIGINT,
            cooldown_until         BIGINT,
            last_evaluated_at      BIGINT,
            last_followup_at       BIGINT,
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # ── 4. alerts table additions ────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS alert_rule_id UUID
            REFERENCES alert_rules(id) ON DELETE SET NULL;
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS is_followup BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_alerts_rule_id
            ON alerts(alert_rule_id)
            WHERE alert_rule_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    raise NotImplementedError("0011_alert_rules is forward-only.")
