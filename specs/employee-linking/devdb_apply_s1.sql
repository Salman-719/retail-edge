-- Dev-DB helper: apply S1 (employee-linking) schema to a database that is stuck at
-- alembic 0008 because the dev image is postgres:16-alpine (no TimescaleDB), so
-- `alembic upgrade head` cannot run migration 0010+.
--
-- This is the SAME DDL as migration 0013_employee_linking.py, made fully idempotent
-- and safe on the 0008 dev DB:
--   * global_identities link columns + index
--   * punch_in_stations, punch_events tables
--   * active_person_state.employee_id — guarded: only runs if that table exists
--     (it is created by migration 0010, which is absent on this dev DB).
--
-- Purely additive (new columns default FALSE/NULL, new tables). No data loss.
-- Apply:  docker exec -i retail-edge-postgres-1 psql -U retailvision -d retailvision -f /tmp/s1.sql
-- (see specs/employee-linking/TESTING.md)

BEGIN;

-- 1. global_identities link columns (also repairs IEP4's is_employee dependency)
ALTER TABLE global_identities
    ADD COLUMN IF NOT EXISTS is_employee BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS employee_id UUID REFERENCES employees(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_global_identities_employee
    ON global_identities(employee_id) WHERE employee_id IS NOT NULL;

-- 2. punch_in_stations
CREATE TABLE IF NOT EXISTS punch_in_stations (
    id               UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id       UUID             NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    store_id         UUID             NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_config_id UUID             NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
    world_x          DOUBLE PRECISION NOT NULL,
    world_y          DOUBLE PRECISION NOT NULL,
    radius_m         DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    created_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT uq_punch_station_per_version UNIQUE (version_id),
    CONSTRAINT positive_radius CHECK (radius_m > 0)
);
CREATE INDEX IF NOT EXISTS idx_punch_stations_version ON punch_in_stations(version_id);

-- 3. punch_events
CREATE TABLE IF NOT EXISTS punch_events (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    employee_id      UUID        NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    punched_at_ms    BIGINT      NOT NULL,
    source           VARCHAR(20) NOT NULL DEFAULT 'device'
                     CHECK (source IN ('device', 'simulated')),
    status           VARCHAR(20) NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'linked', 'unmatched', 'expired')),
    linked_global_id UUID        REFERENCES global_identities(global_id) ON DELETE SET NULL,
    match_distance_m DOUBLE PRECISION,
    attempts         INTEGER     NOT NULL DEFAULT 0,
    last_attempt_at  TIMESTAMPTZ,
    resolved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_punch_events_pending
    ON punch_events(store_id, punched_at_ms) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_punch_events_employee
    ON punch_events(employee_id, punched_at_ms DESC);

-- 4. active_person_state.employee_id — only if the table exists (0010+).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'active_person_state'
    ) THEN
        ALTER TABLE active_person_state
            ADD COLUMN IF NOT EXISTS employee_id UUID REFERENCES employees(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_aps_store_employee_id
            ON active_person_state(store_id, employee_id) WHERE employee_id IS NOT NULL;
        RAISE NOTICE 'active_person_state.employee_id applied';
    ELSE
        RAISE NOTICE 'active_person_state absent (DB < 0010) — skipped; will be added by migration 0013 once 0010 runs';
    END IF;
END $$;

COMMIT;

-- Verify
SELECT 'global_identities link cols' AS check,
       string_agg(column_name, ', ' ORDER BY column_name) AS found
FROM information_schema.columns
WHERE table_name = 'global_identities' AND column_name IN ('is_employee', 'employee_id')
UNION ALL
SELECT 'punch tables',
       string_agg(table_name, ', ' ORDER BY table_name)
FROM information_schema.tables
WHERE table_name IN ('punch_in_stations', 'punch_events');
