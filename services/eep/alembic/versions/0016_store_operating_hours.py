"""Store operating hours replace per-camera camera_schedules (C2).

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-09

Introduces store_operating_hours (PK store_id, day_of_week 0..6 = Mon..Sun) as the
single source of truth for when a store is open. Cameras of the active config
version inherit these hours (see app/tasks/camera_scheduler.py). Seeds each store's
hours from its existing active camera_schedules — for each covered weekday,
is_open=true with open_time = MIN(start_time) and close_time = MAX(end_time) across
that store's schedules for that day; uncovered days → closed — so upgrading does not
silently turn cameras off. Then drops camera_schedules.

The seed is guarded on camera_schedules existing, so a FRESH install (schema.sql
already creates store_operating_hours and no longer creates camera_schedules) runs
this migration cleanly: create is a no-op (IF NOT EXISTS), seed is skipped, drop is
a no-op (IF EXISTS).

Forward-only. downgrade() re-creates camera_schedules EMPTY (prior rows are not
restored) and drops store_operating_hours.
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (a) Table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS store_operating_hours (
            store_id    UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            day_of_week SMALLINT    NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
            is_open     BOOLEAN     NOT NULL DEFAULT FALSE,
            open_time   TIME,
            close_time  TIME,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (store_id, day_of_week)
        );
        """
    )

    # (b) Seed from existing camera_schedules — only if that table is present.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.camera_schedules') IS NOT NULL THEN
                WITH expanded AS (
                    SELECT cs.store_id, dow AS day_of_week, cs.start_time, cs.end_time
                    FROM camera_schedules cs
                    CROSS JOIN LATERAL unnest(cs.days_of_week) AS dow
                    WHERE cs.is_active = true
                ),
                per_day AS (
                    SELECT store_id, day_of_week,
                           MIN(start_time) AS open_time,
                           MAX(end_time)   AS close_time
                    FROM expanded
                    GROUP BY store_id, day_of_week
                ),
                stores_with_sched AS (
                    SELECT DISTINCT store_id FROM expanded
                )
                INSERT INTO store_operating_hours
                    (store_id, day_of_week, is_open, open_time, close_time, updated_at)
                SELECT sw.store_id,
                       d.day,
                       (pd.store_id IS NOT NULL) AS is_open,
                       pd.open_time,
                       pd.close_time,
                       now()
                FROM stores_with_sched sw
                CROSS JOIN generate_series(0, 6) AS d(day)
                LEFT JOIN per_day pd
                       ON pd.store_id = sw.store_id AND pd.day_of_week = d.day
                ON CONFLICT (store_id, day_of_week) DO NOTHING;
            END IF;
        END $$;
        """
    )

    # (c) Retire the per-camera schedule table.
    op.execute("DROP TABLE IF EXISTS camera_schedules;")


def downgrade() -> None:
    # Re-create camera_schedules EMPTY (data not restored) and drop the new table.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_schedules (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            camera_config_id UUID        NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
            days_of_week     INTEGER[]   NOT NULL,
            start_time       TIME        NOT NULL,
            end_time         TIME        NOT NULL,
            is_active        BOOLEAN     NOT NULL DEFAULT true,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("DROP TABLE IF EXISTS store_operating_hours;")
