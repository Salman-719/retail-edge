"""Analytics foundation: hypertables, live state, zone/visit logs, analytics schema.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-08

SPEC-001. Builds the schema contract shared by IEP3 (writer of
global_tracking_history), IEP4 (live state + zone/visit logs), and IEP5
(analytics rollups). Idempotent throughout (IF NOT EXISTS / DROP IF EXISTS /
if_not_exists => TRUE) so it is safe to replay.

Runs under AUTOCOMMIT (see env.py) directly against postgres:5432 — required
because `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)` and the
hypertable conversions must not execute inside a transaction block. Each
TimescaleDB call is therefore its own single-statement op.execute().

Deviations from the SPEC-001 draft (the draft assumed a timestamp time
dimension and a stale migration head):
  * Numbered 0010, not 0004 — 0004 is taken (batch_number_bigint) and the
    chain head was 0009.
  * INTEGER TIME DIMENSION. global_tracking_history.timestamp_ms and
    heatmap_hourly.hour_bucket are BIGINT epoch-ms. TimescaleDB rejects
    INTERVAL-based retention/compression/continuous-aggregate policies on
    integer time columns, so every INTERVAL was converted to integer ms and an
    integer-now function (public.epoch_now_ms) is registered on both
    hypertables:
        90 days  -> 7776000000 ms      7 days  -> 604800000 ms
        30 days  -> 2592000000 ms      2 hours -> 7200000 ms
        5 min    -> 300000 ms          15 min  -> 900000 ms  (bucket)
    schedule_interval stays a real INTERVAL (wall-clock job cadence).
  * COMPOSITE PRIMARY KEY. create_hypertable requires the partition column in
    every unique/PK. global_tracking_history's PK was (id); changed to
    (id, timestamp_ms) before conversion. (heatmap_hourly's PK already
    includes hour_bucket.)
  * CONTINUOUS AGGREGATE has no COUNT(DISTINCT). TimescaleDB caggs do not
    support DISTINCT aggregates, so zone_occupancy_15min keeps only
    total_observations = COUNT(*); IEP5 computes exact unique_visitors from
    raw global_tracking_history (user decision).
  * Section 1's idx_tracking_history_camera_window is SKIPPED — the existing
    idx_tracking_history_camera_ts already indexes (camera_id, timestamp_ms);
    a second identical index would be pure write overhead.
  * The pre-existing non-unique idx_gth_global_ts is DROPPED — the new unique
    idx_gth_unique_bucket covers the same (global_id, timestamp_ms) lookups.

These objects are migration-only (never in schema.sql) because the timescaledb
extension is created in migration 0001, after initdb applies schema.sql.
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 0. Integer-now function for integer-time hypertables ─────────────────
    # TimescaleDB needs a "now" function to schedule retention/compression and
    # to drive continuous-aggregate refresh on integer time dimensions.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.epoch_now_ms() RETURNS BIGINT
        LANGUAGE SQL STABLE AS $$
            SELECT (EXTRACT(EPOCH FROM now()) * 1000)::BIGINT
        $$;
        """
    )

    # ── 1. tracking_history delete index ─────────────────────────────────────
    # SKIPPED: idx_tracking_history_camera_ts already indexes
    # (camera_id, timestamp_ms). No duplicate created.

    # ── 2. global_tracking_history -> hypertable ─────────────────────────────
    # 2a. PK must include the time partition column for create_hypertable.
    op.execute(
        "ALTER TABLE global_tracking_history "
        "DROP CONSTRAINT IF EXISTS global_tracking_history_pkey;"
    )
    op.execute(
        "ALTER TABLE global_tracking_history "
        "ADD PRIMARY KEY (id, timestamp_ms);"
    )
    # 2b. One row per person per 5s bucket; supports IEP3 ON CONFLICT DO NOTHING.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_gth_unique_bucket "
        "ON global_tracking_history(global_id, timestamp_ms);"
    )
    # 2c. Redundant now that the unique index covers the same columns.
    op.execute("DROP INDEX IF EXISTS idx_gth_global_ts;")
    # 2d. Convert to hypertable (integer time, 1-day chunks in ms).
    op.execute(
        "SELECT create_hypertable('global_tracking_history', 'timestamp_ms', "
        "chunk_time_interval => 86400000::BIGINT, "
        "if_not_exists => TRUE, migrate_data => TRUE);"
    )
    # 2e. Register integer-now so time-based jobs know the cutoff.
    op.execute(
        "SELECT set_integer_now_func('global_tracking_history', "
        "'public.epoch_now_ms', replace_if_exists => TRUE);"
    )
    # 2f. Retention — 90 days.
    op.execute(
        "SELECT add_retention_policy('global_tracking_history', "
        "drop_after => 7776000000::BIGINT, if_not_exists => TRUE);"
    )
    # 2g. Compression — chunks older than 7 days.
    # All four FK columns (store_id, global_id, version_id, zone_id) must appear
    # in compress_segmentby, otherwise TimescaleDB refuses compression because
    # the FK constraints can't be enforced on compressed chunks. The spec listed
    # only store_id, global_id; version_id and zone_id are added here. They are
    # low/moderate cardinality and common filter keys, so the impact on the
    # compression ratio (already bounded by global_id) is negligible.
    op.execute(
        "ALTER TABLE global_tracking_history SET ("
        "timescaledb.compress, "
        "timescaledb.compress_orderby = 'timestamp_ms DESC', "
        "timescaledb.compress_segmentby = 'store_id, global_id, version_id, zone_id');"
    )
    op.execute(
        "SELECT add_compression_policy('global_tracking_history', "
        "compress_after => 604800000::BIGINT, if_not_exists => TRUE);"
    )

    # ── 3. zone_occupancy_15min — continuous aggregate ───────────────────────
    # Must be its own statement (cannot run inside a transaction block).
    # COUNT(DISTINCT) is unsupported in caggs; uniques computed by IEP5 from raw.
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS zone_occupancy_15min
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(900000::BIGINT, timestamp_ms) AS bucket_ms,
            store_id,
            zone_id,
            COUNT(*) AS total_observations
        FROM global_tracking_history
        WHERE zone_id IS NOT NULL
        GROUP BY bucket_ms, store_id, zone_id
        WITH NO DATA;
        """
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy('zone_occupancy_15min', "
        "start_offset => 7200000::BIGINT, end_offset => 300000::BIGINT, "
        "schedule_interval => INTERVAL '5 minutes', if_not_exists => TRUE);"
    )

    # ── 4. active_person_state — IEP4 live state (mutable, NOT a hypertable) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS active_person_state (
            global_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL
                                    REFERENCES stores(id) ON DELETE CASCADE,
            current_zone_id         UUID        REFERENCES zones(id) ON DELETE SET NULL,
            entered_current_zone_at BIGINT,
            last_seen_at            BIGINT      NOT NULL,
            last_batch_number       BIGINT      NOT NULL,
            is_employee             BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (global_id, store_id)
        );

        CREATE INDEX IF NOT EXISTS idx_aps_store_zone
            ON active_person_state(store_id, current_zone_id)
            WHERE current_zone_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_aps_store_employee
            ON active_person_state(store_id, is_employee);
        CREATE INDEX IF NOT EXISTS idx_aps_store_last_seen
            ON active_person_state(store_id, last_seen_at);
        """
    )

    # ── 5. zone_transition_log — IEP4 append-only closed sessions ────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS zone_transition_log (
            id            BIGSERIAL   PRIMARY KEY,
            global_id     UUID        NOT NULL,
            store_id      UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            zone_id       UUID        NOT NULL REFERENCES zones(id) ON DELETE SET NULL,
            entered_at_ms BIGINT      NOT NULL,
            exited_at_ms  BIGINT      NOT NULL,
            dwell_ms      BIGINT      NOT NULL
                          GENERATED ALWAYS AS (exited_at_ms - entered_at_ms) STORED,
            is_employee   BOOLEAN     NOT NULL DEFAULT FALSE,
            entry_batch   BIGINT      NOT NULL,
            exit_batch    BIGINT      NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT positive_dwell CHECK (exited_at_ms > entered_at_ms)
        );

        CREATE INDEX IF NOT EXISTS idx_ztl_store_zone
            ON zone_transition_log(store_id, zone_id, entered_at_ms);
        CREATE INDEX IF NOT EXISTS idx_ztl_global_id
            ON zone_transition_log(global_id, entered_at_ms);
        CREATE INDEX IF NOT EXISTS idx_ztl_store_ts
            ON zone_transition_log(store_id, entered_at_ms);
        CREATE INDEX IF NOT EXISTS idx_ztl_employee
            ON zone_transition_log(store_id, is_employee, entered_at_ms);
        """
    )

    # ── 6. visit_sessions — IEP4 append-only visit log ───────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS visit_sessions (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            global_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            entered_at_ms     BIGINT      NOT NULL,
            exited_at_ms      BIGINT,
            total_duration_ms BIGINT
                              GENERATED ALWAYS AS (exited_at_ms - entered_at_ms) STORED,
            entry_zone_id     UUID        REFERENCES zones(id) ON DELETE SET NULL,
            exit_zone_id      UUID        REFERENCES zones(id) ON DELETE SET NULL,
            is_employee       BOOLEAN     NOT NULL DEFAULT FALSE,
            zones_visited     INTEGER     NOT NULL DEFAULT 0,
            version_id        UUID        REFERENCES store_config_versions(id) ON DELETE SET NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT positive_duration
                CHECK (exited_at_ms IS NULL OR exited_at_ms > entered_at_ms)
        );

        CREATE INDEX IF NOT EXISTS idx_vs_store_ts
            ON visit_sessions(store_id, entered_at_ms);
        CREATE INDEX IF NOT EXISTS idx_vs_global_id
            ON visit_sessions(global_id);
        CREATE INDEX IF NOT EXISTS idx_vs_store_employee
            ON visit_sessions(store_id, is_employee);
        """
    )

    # ── 7. analytics schema + daily tables ───────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics;")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.daily_store_summary (
            id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                 UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            date                     DATE        NOT NULL,
            total_visits             INTEGER     NOT NULL DEFAULT 0,
            unique_visitors          INTEGER     NOT NULL DEFAULT 0,
            avg_visit_duration_ms    BIGINT,
            median_visit_duration_ms BIGINT,
            peak_occupancy           INTEGER,
            peak_occupancy_at_ms     BIGINT,
            dead_period_count        INTEGER     NOT NULL DEFAULT 0,
            dead_period_total_ms     BIGINT      NOT NULL DEFAULT 0,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_store_date UNIQUE (store_id, date)
        );

        CREATE TABLE IF NOT EXISTS analytics.daily_zone_summary (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id            UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            zone_id             UUID        NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
            date                DATE        NOT NULL,
            unique_visitors     INTEGER     NOT NULL DEFAULT 0,
            total_transitions   INTEGER     NOT NULL DEFAULT 0,
            avg_dwell_ms        BIGINT,
            median_dwell_ms     BIGINT,
            max_concurrent      INTEGER,
            passthrough_count   INTEGER     NOT NULL DEFAULT 0,
            engagement_count    INTEGER     NOT NULL DEFAULT 0,
            alert_trigger_count INTEGER     NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_store_zone_date UNIQUE (store_id, zone_id, date)
        );

        CREATE TABLE IF NOT EXISTS analytics.daily_employee_summary (
            id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                  UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            employee_id               UUID        NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            date                      DATE        NOT NULL,
            scheduled_duration_ms     BIGINT,
            present_duration_ms       BIGINT,
            presence_ratio            FLOAT,
            zone_punctuality_delay_ms BIGINT,
            unassigned_zone_time_ms   BIGINT,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_employee_date UNIQUE (store_id, employee_id, date)
        );

        CREATE TABLE IF NOT EXISTS analytics.visit_duration_distribution (
            store_id      UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            date          DATE        NOT NULL,
            bucket_label  VARCHAR(20) NOT NULL,
            bucket_min_ms BIGINT      NOT NULL,
            bucket_max_ms BIGINT,
            visit_count   INTEGER     NOT NULL DEFAULT 0,
            PRIMARY KEY (store_id, date, bucket_label)
        );

        CREATE TABLE IF NOT EXISTS analytics.zone_sequence_matrix (
            store_id         UUID    NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            date             DATE    NOT NULL,
            from_zone_id     UUID    REFERENCES zones(id) ON DELETE SET NULL,
            to_zone_id       UUID    REFERENCES zones(id) ON DELETE SET NULL,
            transition_count INTEGER NOT NULL DEFAULT 0,
            probability      FLOAT,
            PRIMARY KEY (store_id, date, from_zone_id, to_zone_id)
        );
        """
    )

    # ── 8. Weekly + monthly rollups (plain upserted tables, never hypertables) ─
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.weekly_store_summary (
            id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                 UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            iso_year                 INTEGER     NOT NULL,
            iso_week                 INTEGER     NOT NULL,
            week_start_date          DATE        NOT NULL,
            total_visits             INTEGER     NOT NULL DEFAULT 0,
            unique_visitors          INTEGER     NOT NULL DEFAULT 0,
            avg_visit_duration_ms    BIGINT,
            median_visit_duration_ms BIGINT,
            peak_occupancy           INTEGER,
            dead_period_count        INTEGER     NOT NULL DEFAULT 0,
            is_complete              BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_store_week UNIQUE (store_id, iso_year, iso_week)
        );

        CREATE TABLE IF NOT EXISTS analytics.weekly_zone_summary (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id          UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            zone_id           UUID        NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
            iso_year          INTEGER     NOT NULL,
            iso_week          INTEGER     NOT NULL,
            unique_visitors   INTEGER     NOT NULL DEFAULT 0,
            avg_dwell_ms      BIGINT,
            median_dwell_ms   BIGINT,
            passthrough_count INTEGER     NOT NULL DEFAULT 0,
            engagement_count  INTEGER     NOT NULL DEFAULT 0,
            is_complete       BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_store_zone_week UNIQUE (store_id, zone_id, iso_year, iso_week)
        );

        CREATE TABLE IF NOT EXISTS analytics.weekly_employee_summary (
            id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                 UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            employee_id              UUID        NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            iso_year                 INTEGER     NOT NULL,
            iso_week                 INTEGER     NOT NULL,
            scheduled_duration_ms    BIGINT,
            present_duration_ms      BIGINT,
            avg_presence_ratio       FLOAT,
            avg_punctuality_delay_ms BIGINT,
            is_complete              BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_employee_week UNIQUE (store_id, employee_id, iso_year, iso_week)
        );

        CREATE TABLE IF NOT EXISTS analytics.monthly_store_summary (
            id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                 UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            year                     INTEGER     NOT NULL,
            month                    INTEGER     NOT NULL,
            month_start_date         DATE        NOT NULL,
            total_visits             INTEGER     NOT NULL DEFAULT 0,
            unique_visitors          INTEGER     NOT NULL DEFAULT 0,
            avg_visit_duration_ms    BIGINT,
            median_visit_duration_ms BIGINT,
            peak_occupancy           INTEGER,
            dead_period_count        INTEGER     NOT NULL DEFAULT 0,
            is_complete              BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_store_month UNIQUE (store_id, year, month)
        );

        CREATE TABLE IF NOT EXISTS analytics.monthly_zone_summary (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id          UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            zone_id           UUID        NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
            year              INTEGER     NOT NULL,
            month             INTEGER     NOT NULL,
            unique_visitors   INTEGER     NOT NULL DEFAULT 0,
            avg_dwell_ms      BIGINT,
            median_dwell_ms   BIGINT,
            passthrough_count INTEGER     NOT NULL DEFAULT 0,
            engagement_count  INTEGER     NOT NULL DEFAULT 0,
            is_complete       BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_store_zone_month UNIQUE (store_id, zone_id, year, month)
        );

        CREATE TABLE IF NOT EXISTS analytics.monthly_employee_summary (
            id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id                 UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            employee_id              UUID        NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            year                     INTEGER     NOT NULL,
            month                    INTEGER     NOT NULL,
            scheduled_duration_ms    BIGINT,
            present_duration_ms      BIGINT,
            avg_presence_ratio       FLOAT,
            avg_punctuality_delay_ms BIGINT,
            is_complete              BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT unique_employee_month UNIQUE (store_id, employee_id, year, month)
        );
        """
    )

    # ── 9. Heatmap tables ────────────────────────────────────────────────────
    # heatmap_hourly is a hypertable; its PK already includes the time column.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.heatmap_hourly (
            store_id    UUID    NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            version_id  UUID    REFERENCES store_config_versions(id) ON DELETE SET NULL,
            hour_bucket BIGINT  NOT NULL,
            grid_x      INTEGER NOT NULL,
            grid_y      INTEGER NOT NULL,
            hit_count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (store_id, hour_bucket, grid_x, grid_y)
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('analytics.heatmap_hourly', 'hour_bucket', "
        "chunk_time_interval => 604800000::BIGINT, if_not_exists => TRUE);"
    )
    op.execute(
        "SELECT set_integer_now_func('analytics.heatmap_hourly', "
        "'public.epoch_now_ms', replace_if_exists => TRUE);"
    )
    # version_id is added to segmentby for the same FK-compatibility reason as
    # global_tracking_history (store_id + version_id are heatmap_hourly's FKs).
    op.execute(
        "ALTER TABLE analytics.heatmap_hourly SET ("
        "timescaledb.compress, "
        "timescaledb.compress_orderby = 'hour_bucket DESC', "
        "timescaledb.compress_segmentby = 'store_id, version_id');"
    )
    op.execute(
        "SELECT add_compression_policy('analytics.heatmap_hourly', "
        "compress_after => 2592000000::BIGINT, if_not_exists => TRUE);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_hh_store_bucket "
        "ON analytics.heatmap_hourly(store_id, hour_bucket DESC);"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.heatmap_daily (
            store_id   UUID    NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            version_id UUID    REFERENCES store_config_versions(id) ON DELETE SET NULL,
            date       DATE    NOT NULL,
            grid_x     INTEGER NOT NULL,
            grid_y     INTEGER NOT NULL,
            hit_count  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (store_id, date, grid_x, grid_y)
        );
        CREATE INDEX IF NOT EXISTS idx_hd_store_date
            ON analytics.heatmap_daily(store_id, date DESC);

        CREATE TABLE IF NOT EXISTS analytics.heatmap_weekly (
            store_id    UUID    NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            iso_year    INTEGER NOT NULL,
            iso_week    INTEGER NOT NULL,
            grid_x      INTEGER NOT NULL,
            grid_y      INTEGER NOT NULL,
            hit_count   INTEGER NOT NULL DEFAULT 0,
            is_complete BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (store_id, iso_year, iso_week, grid_x, grid_y)
        );

        CREATE TABLE IF NOT EXISTS analytics.heatmap_monthly (
            store_id    UUID    NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            year        INTEGER NOT NULL,
            month       INTEGER NOT NULL,
            grid_x      INTEGER NOT NULL,
            grid_y      INTEGER NOT NULL,
            hit_count   INTEGER NOT NULL DEFAULT 0,
            is_complete BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (store_id, year, month, grid_x, grid_y)
        );
        """
    )

    # ── 10. Indexes on analytics daily/rollup tables ─────────────────────────
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dss_store_date
            ON analytics.daily_store_summary(store_id, date DESC);
        CREATE INDEX IF NOT EXISTS idx_dzs_store_date
            ON analytics.daily_zone_summary(store_id, date DESC);
        CREATE INDEX IF NOT EXISTS idx_dzs_zone_date
            ON analytics.daily_zone_summary(zone_id, date DESC);
        CREATE INDEX IF NOT EXISTS idx_des_store_date
            ON analytics.daily_employee_summary(store_id, date DESC);
        CREATE INDEX IF NOT EXISTS idx_des_employee_date
            ON analytics.daily_employee_summary(employee_id, date DESC);
        CREATE INDEX IF NOT EXISTS idx_wss_store
            ON analytics.weekly_store_summary(store_id, iso_year DESC, iso_week DESC);
        CREATE INDEX IF NOT EXISTS idx_mss_store
            ON analytics.monthly_store_summary(store_id, year DESC, month DESC);
        """
    )


def downgrade() -> None:
    # Forward-only analytics foundation. Tearing down hypertables, continuous
    # aggregates, policies, and the analytics schema is out of scope.
    raise NotImplementedError(
        "0010_analytics_foundation is forward-only."
    )
