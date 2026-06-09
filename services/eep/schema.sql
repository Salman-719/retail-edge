-- RetailVision EEP — full database schema
-- Domains 1–8 (Milestones 1–3)
-- Run once against a fresh database: psql $DATABASE_URL -f schema.sql

-- ============================================================================
-- DOMAIN 1 — Identity & Access
-- ============================================================================

CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_type   VARCHAR(20) NOT NULL
                   CHECK (account_type IN ('owner', 'sub_account')),
    email          VARCHAR(255) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    auth_provider  VARCHAR(20) NOT NULL DEFAULT 'local'
                   CHECK (auth_provider IN ('local', 'google', 'microsoft')),
    name           VARCHAR(255) NOT NULL,
    is_super_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    last_active_at TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT owner_has_no_creator
        CHECK (account_type = 'sub_account' OR created_by IS NULL)
);

-- stores: Domain 1 stub + Domain 2 columns merged
CREATE TABLE stores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) UNIQUE NOT NULL,
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    timezone        VARCHAR(100) NOT NULL DEFAULT 'Asia/Beirut',
    address         TEXT,
    currency        VARCHAR(10) NOT NULL DEFAULT 'USD'
                    CHECK (currency IN ('USD', 'LBP')),
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'suspended', 'archived')),
    logo_s3_key     VARCHAR(500),
    operating_hours JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_slug CHECK (slug ~ '^[a-z0-9-]+$')
);

CREATE TABLE store_members (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    store_id     UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    role         VARCHAR(20) NOT NULL CHECK (role IN ('manager', 'viewer')),
    invited_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT one_membership_per_user_per_store UNIQUE (user_id, store_id)
);

CREATE TABLE store_member_permissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_member_id UUID NOT NULL REFERENCES store_members(id) ON DELETE CASCADE,
    permission      VARCHAR(50) NOT NULL CHECK (permission IN (
                        'view_alerts', 'view_analytics', 'view_heatmaps',
                        'view_employees', 'view_audit_log',
                        'receive_notifications', 'manage_employees',
                        'manage_shifts'
                    )),
    granted         BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT unique_member_permission UNIQUE (store_member_id, permission)
);

CREATE TABLE invitations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id      UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    invited_email VARCHAR(255) NOT NULL,
    role          VARCHAR(20) NOT NULL CHECK (role IN ('manager', 'viewer')),
    permissions   JSONB NOT NULL DEFAULT '{}',
    token         VARCHAR(255) UNIQUE NOT NULL,
    invited_by    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at    TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '3 days'),
    accepted_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT not_expired_when_accepted
        CHECK (accepted_at IS NULL OR accepted_at <= expires_at)
);

CREATE TABLE refresh_tokens (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id     UUID REFERENCES stores(id) ON DELETE SET NULL,
    user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    action       VARCHAR(50) NOT NULL,  -- validated in app: app/core/audit_actions.py (AUDIT_ACTIONS)
    entity_type  VARCHAR(50),
    entity_id    UUID,
    before_state JSONB,
    after_state  JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- DOMAIN 2 — Store Structure (continued)
-- ============================================================================

-- store_config_versions: includes diff_from_previous (Domain 7)
CREATE TABLE store_config_versions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id           UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    label              VARCHAR(255),
    status             VARCHAR(20) NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'active', 'archived')),
    active_from        TIMESTAMPTZ,
    active_until       TIMESTAMPTZ,
    last_edited_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at         TIMESTAMPTZ,
    warning_sent_at    TIMESTAMPTZ,
    created_by         UUID NOT NULL REFERENCES users(id),
    activated_by       UUID REFERENCES users(id),
    discarded_by       UUID REFERENCES users(id),
    diff_from_previous JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT active_has_active_from
        CHECK (status != 'active' OR active_from IS NOT NULL),
    CONSTRAINT active_until_after_from
        CHECK (active_until IS NULL OR active_until > active_from),
    CONSTRAINT draft_has_no_active_from
        CHECK (status != 'draft' OR active_from IS NULL)
);

CREATE UNIQUE INDEX one_draft_per_store
    ON store_config_versions (store_id) WHERE status = 'draft';
CREATE UNIQUE INDEX one_active_per_store
    ON store_config_versions (store_id) WHERE status = 'active';

-- ============================================================================
-- DOMAIN 6 — Calibration (coordinate_frames before floor_plans)
-- ============================================================================

CREATE TABLE coordinate_frames (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id           UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    version_id         UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    origin_description TEXT,
    x_axis_description TEXT,
    units              VARCHAR(20) NOT NULL DEFAULT 'meters',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_frame_per_version UNIQUE (version_id, store_id)
);

-- ============================================================================
-- DOMAIN 3 — Floor Plan & Spatial
-- ============================================================================

-- floor_plans: includes coordinate_frame_id (Domain 6)
CREATE TABLE floor_plans (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id          UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    store_id            UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    onboarding_method   VARCHAR(20) NOT NULL
                        CHECK (onboarding_method IN ('standard', 'calibration_files')),
    original_s3_key     VARCHAR(500),
    display_s3_key      VARCHAR(500),
    width_px            INTEGER,
    height_px           INTEGER,
    origin_x            FLOAT,
    origin_y            FLOAT,
    pixels_per_meter    FLOAT,
    world_x_min         FLOAT,
    world_x_max         FLOAT,
    world_y_min         FLOAT,
    world_y_max         FLOAT,
    boundary_polygon        JSONB,
    image_uploaded      BOOLEAN NOT NULL DEFAULT FALSE,
    scale_defined       BOOLEAN NOT NULL DEFAULT FALSE,
    coordinate_frame_id UUID REFERENCES coordinate_frames(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_floor_plan_per_version UNIQUE (version_id, store_id),
    CONSTRAINT method1_requires_image
        CHECK (onboarding_method != 'standard' OR (
            NOT image_uploaded OR (
                original_s3_key IS NOT NULL AND
                display_s3_key  IS NOT NULL AND
                width_px        IS NOT NULL AND
                height_px       IS NOT NULL
            ))),
    CONSTRAINT method1_scale_fields
        CHECK (NOT scale_defined OR (
            origin_x         IS NOT NULL AND
            origin_y         IS NOT NULL AND
            pixels_per_meter IS NOT NULL
        ))
);

CREATE TABLE zones (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id              UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    store_id                UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    name                    VARCHAR(255) NOT NULL,
    type                    VARCHAR(30) NOT NULL
                            CHECK (type IN (
                                'entrance', 'checkout', 'aisle',
                                'staff_only', 'general'
                            )),
    points                  JSONB NOT NULL,
    queue_threshold_people  INTEGER,
    queue_threshold_minutes INTEGER,
    staff_absence_minutes   INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT zone_name_unique_per_version UNIQUE (version_id, store_id, name)
);

CREATE TABLE obstacles (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    store_id   UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    name       VARCHAR(255),
    points     JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- DOMAIN 4 — Cameras & Streams
-- ============================================================================

CREATE TABLE physical_cameras (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    name             VARCHAR(255) NOT NULL,
    cloud_stream_url VARCHAR(500),
    stream_username  VARCHAR(255),
    stream_password  VARCHAR(500),
    brand            VARCHAR(100),
    model            VARCHAR(100),
    mounting         VARCHAR(20) DEFAULT 'ceiling'
                     CHECK (mounting IN ('ceiling', 'wall', 'corner')),
    health_status    VARCHAR(20) NOT NULL DEFAULT 'offline'
                     CHECK (health_status IN ('online', 'offline', 'degraded')),
    last_seen_at     TIMESTAMPTZ,
    last_error       TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- camera_configs: includes frame_quality fields (Domain 8)
CREATE TABLE camera_configs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id          UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    physical_camera_id  UUID NOT NULL REFERENCES physical_cameras(id) ON DELETE CASCADE,
    store_id            UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    position_x          FLOAT NOT NULL,
    position_y          FLOAT NOT NULL,
    height_meters       FLOAT,
    viewing_angle_deg   FLOAT,
    fov_deg             FLOAT,
    frame_s3_key        VARCHAR(500),
    frame_captured_at   TIMESTAMPTZ,
    frame_source        VARCHAR(20) DEFAULT 'manual'
                        CHECK (frame_source IN ('manual', 'snapshot')),
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending', 'frame_uploaded',
                            'calibrated', 'verified'
                        )),
    video_s3_key        VARCHAR(500),
    video_fps           FLOAT,
    video_duration      FLOAT,
    video_width         INTEGER,
    video_height        INTEGER,
    frame_quality_score FLOAT,
    frame_quality_flags JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_camera_per_version UNIQUE (version_id, physical_camera_id)
);

CREATE TABLE camera_zone_coverage (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_config_id UUID NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
    zone_id          UUID NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    coverage_percent FLOAT,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_camera_zone UNIQUE (camera_config_id, zone_id)
);

-- ============================================================================
-- DOMAIN 5 — Employees & Shifts
-- ============================================================================

CREATE TABLE employees (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id             UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    name                 VARCHAR(255) NOT NULL,
    role                 VARCHAR(100),
    employee_code        VARCHAR(100),
    phone                VARCHAR(50),
    email                VARCHAR(255),
    enrollment_status    VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (enrollment_status IN (
                             'pending', 'enrolled', 'needs_update'
                         )),
    last_enrolled_at     TIMESTAMPTZ,
    is_on_shift          BOOLEAN NOT NULL DEFAULT FALSE,
    break_status         VARCHAR(20) NOT NULL DEFAULT 'none'
                         CHECK (break_status IN ('none', 'on_break')),
    break_started_at     TIMESTAMPTZ,
    last_seen_at         TIMESTAMPTZ,
    last_seen_zone_id    UUID REFERENCES zones(id) ON DELETE SET NULL,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_employee_code_per_store
        UNIQUE (store_id, employee_code)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE employee_embeddings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id      UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    embedding        JSONB NOT NULL,
    source           VARCHAR(20) NOT NULL
                     CHECK (source IN ('enrollment', 'operational', 'punch_in')),
    confidence       FLOAT,
    camera_config_id UUID REFERENCES camera_configs(id) ON DELETE SET NULL,
    frame_s3_key     VARCHAR(500),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    captured_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE shift_patterns (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    day_of_week        SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time         TIME NOT NULL,
    end_time           TIME NOT NULL,
    break_duration_min INTEGER NOT NULL DEFAULT 0,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT end_after_start CHECK (end_time > start_time)
);

CREATE TABLE shift_instances (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    shift_pattern_id   UUID REFERENCES shift_patterns(id) ON DELETE SET NULL,
    scheduled_start    TIMESTAMPTZ NOT NULL,
    scheduled_end      TIMESTAMPTZ NOT NULL,
    break_duration_min INTEGER NOT NULL DEFAULT 0,
    actual_start       TIMESTAMPTZ,
    actual_end         TIMESTAMPTZ,
    status             VARCHAR(20) NOT NULL DEFAULT 'scheduled'
                       CHECK (status IN (
                           'scheduled', 'active', 'completed',
                           'absent', 'cancelled'
                       )),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT scheduled_end_after_start CHECK (scheduled_end > scheduled_start)
);

CREATE TABLE alert_configs (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id                 UUID NOT NULL UNIQUE REFERENCES stores(id) ON DELETE CASCADE,
    shift_start_grace_min    INTEGER NOT NULL DEFAULT 15,
    absence_threshold_min    INTEGER NOT NULL DEFAULT 15,
    queue_people_threshold   INTEGER NOT NULL DEFAULT 10,
    queue_wait_min_threshold INTEGER NOT NULL DEFAULT 7,
    queue_alert_cooldown_min INTEGER NOT NULL DEFAULT 15,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE alerts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id    UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    type        VARCHAR(30) NOT NULL
                CHECK (type IN (
                    'staff_absence', 'queue_buildup',
                    'camera_offline', 'camera_degraded'
                )),
    employee_id UUID REFERENCES employees(id) ON DELETE SET NULL,
    zone_id     UUID REFERENCES zones(id) ON DELETE SET NULL,
    details     JSONB,
    resolved_at TIMESTAMPTZ,
    resolution  VARCHAR(20) CHECK (resolution IN ('auto_detected', 'manual_dismiss')),
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- DOMAIN 6 — Calibration (continued)
-- ============================================================================

CREATE TABLE calibrations (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_config_id       UUID NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
    method                 VARCHAR(20) NOT NULL
                           CHECK (method IN ('homography', 'calibration_files')),
    status                 VARCHAR(20) NOT NULL DEFAULT 'pending'
                           CHECK (status IN (
                               'pending', 'ok', 'verified', 'rejected', 'failed'
                           )),
    is_current             BOOLEAN NOT NULL DEFAULT FALSE,

    -- Method 1: Homography
    correspondences        JSONB,
    homography_matrix      JSONB,
    rms_reprojection_error FLOAT,
    max_reprojection_error FLOAT,
    point_count            INTEGER,
    coverage_score         FLOAT,
    condition_number       FLOAT,

    -- Method 2: Calibration Files
    intrinsic_file_s3_key  VARCHAR(500),
    extrinsic_file_s3_key  VARCHAR(500),
    intrinsic_matrix       JSONB,
    dist_coeffs            JSONB,
    rotation_vector        JSONB,
    rotation_matrix        JSONB,
    translation_vector     JSONB,
    camera_world_x         FLOAT,
    camera_world_y         FLOAT,
    camera_world_z         FLOAT,
    image_width            INTEGER,
    image_height           INTEGER,

    -- Verification
    verified_at            TIMESTAMPTZ,
    verified_by            UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Audit
    computed_at            TIMESTAMPTZ,
    computation_error      TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT verified_requires_computation
        CHECK (
            status != 'verified' OR
            rms_reprojection_error IS NOT NULL OR
            intrinsic_matrix IS NOT NULL OR
            coverage_score IS NOT NULL
        ),
    CONSTRAINT homography_has_matrix
        CHECK (
            method != 'homography' OR
            status IN ('pending', 'failed') OR
            homography_matrix IS NOT NULL
        ),
    CONSTRAINT calibration_files_has_intrinsics
        CHECK (
            method != 'calibration_files' OR
            status IN ('pending', 'failed') OR
            intrinsic_matrix IS NOT NULL
        )
);

-- ============================================================================
-- DOMAIN 7 — Config Versioning Logic
-- ============================================================================

CREATE TABLE store_settings (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id                    UUID NOT NULL UNIQUE REFERENCES stores(id) ON DELETE CASCADE,
    activation_countdown_sec    INTEGER NOT NULL DEFAULT 60,
    chunk_duration_sec          INTEGER NOT NULL DEFAULT 300,
    chunk_overlap_sec           INTEGER NOT NULL DEFAULT 30,
    frame_sample_rate_fps       INTEGER NOT NULL DEFAULT 5,
    active_config_cache_ttl_sec INTEGER NOT NULL DEFAULT 300,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE version_sync_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id      UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    version_id    UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    event_type    VARCHAR(20) NOT NULL CHECK (event_type IN ('activation', 'rollback')),
    countdown_sec INTEGER NOT NULL,
    initiated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    initiated_by  UUID NOT NULL REFERENCES users(id),
    scheduled_at  TIMESTAMPTZ NOT NULL,
    iep1_ack_at   TIMESTAMPTZ,
    iep2_ack_at   TIMESTAMPTZ,
    iep3_ack_at   TIMESTAMPTZ,
    iep4_ack_at   TIMESTAMPTZ,
    iep5_ack_at   TIMESTAMPTZ,
    executed_at   TIMESTAMPTZ,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'executed', 'cancelled', 'failed')),
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- DOMAIN 8 — Test Mode & Stream Verification
-- ============================================================================

CREATE TABLE test_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id     UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    version_id   UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    initiated_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'processing', 'complete', 'failed')),
    expires_at   TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE test_run_cameras (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_run_id        UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    physical_camera_id UUID NOT NULL REFERENCES physical_cameras(id) ON DELETE CASCADE,
    camera_config_id   UUID NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
    video_s3_key       VARCHAR(500) NOT NULL,
    video_fps          FLOAT,
    video_duration     FLOAT,
    video_width        INTEGER,
    video_height       INTEGER,
    iep1_status        VARCHAR(20) DEFAULT 'pending'
                       CHECK (iep1_status IN ('pending', 'processing', 'complete', 'failed')),
    frames_sampled     INTEGER,
    frames_dropped     INTEGER,
    quality_score      FLOAT,
    iep2_status        VARCHAR(20) DEFAULT 'pending'
                       CHECK (iep2_status IN ('pending', 'processing', 'complete', 'failed')),
    trajectory_data    JSONB,
    zone_occupancy     JSONB,
    heatmap_s3_key     VARCHAR(500),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_camera_per_test_run UNIQUE (test_run_id, physical_camera_id)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Domain 1
CREATE INDEX idx_users_email            ON users(email);
CREATE INDEX idx_users_account_type     ON users(account_type);
CREATE INDEX idx_store_members_user_id  ON store_members(user_id);
CREATE INDEX idx_store_members_store_id ON store_members(store_id);
CREATE INDEX idx_invitations_token      ON invitations(token);
CREATE INDEX idx_invitations_store_id   ON invitations(store_id);
CREATE INDEX idx_invitations_email      ON invitations(invited_email);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash    ON refresh_tokens(token_hash);
CREATE INDEX idx_audit_logs_store_id    ON audit_logs(store_id);
CREATE INDEX idx_audit_logs_user_id     ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_created_at  ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_logs_entity      ON audit_logs(entity_type, entity_id);

-- Domain 2
CREATE INDEX idx_stores_slug          ON stores(slug);
CREATE INDEX idx_stores_status        ON stores(status);
CREATE INDEX idx_stores_created_by    ON stores(created_by);
CREATE INDEX idx_versions_store_id    ON store_config_versions(store_id);
CREATE INDEX idx_versions_status      ON store_config_versions(store_id, status);
CREATE INDEX idx_versions_active_from ON store_config_versions(active_from DESC);
CREATE INDEX idx_versions_expires_at  ON store_config_versions(expires_at)
    WHERE status = 'draft';

-- Domain 3
CREATE INDEX idx_floor_plans_version_id ON floor_plans(version_id);
CREATE INDEX idx_floor_plans_store_id   ON floor_plans(store_id);
CREATE INDEX idx_zones_version_id       ON zones(version_id);
CREATE INDEX idx_zones_store_id         ON zones(store_id);
CREATE INDEX idx_zones_type             ON zones(version_id, type);
CREATE INDEX idx_obstacles_version_id   ON obstacles(version_id);
CREATE INDEX idx_obstacles_store_id     ON obstacles(store_id);

-- Domain 4
CREATE INDEX idx_physical_cameras_store_id   ON physical_cameras(store_id);
CREATE INDEX idx_physical_cameras_active     ON physical_cameras(store_id, is_active);
CREATE INDEX idx_physical_cameras_health     ON physical_cameras(health_status);
CREATE INDEX idx_camera_configs_version_id   ON camera_configs(version_id);
CREATE INDEX idx_camera_configs_physical_id  ON camera_configs(physical_camera_id);
CREATE INDEX idx_camera_configs_store_id     ON camera_configs(store_id);
CREATE INDEX idx_camera_configs_status       ON camera_configs(version_id, status);
CREATE INDEX idx_camera_zone_coverage_camera ON camera_zone_coverage(camera_config_id);
CREATE INDEX idx_camera_zone_coverage_zone   ON camera_zone_coverage(zone_id);

-- Domain 5
CREATE INDEX idx_employees_store_id       ON employees(store_id);
CREATE INDEX idx_employees_active         ON employees(store_id, is_active);
CREATE INDEX idx_employees_on_shift       ON employees(store_id, is_on_shift) WHERE is_on_shift = TRUE;
CREATE INDEX idx_employees_last_zone      ON employees(last_seen_zone_id) WHERE last_seen_zone_id IS NOT NULL;
CREATE INDEX idx_embeddings_employee      ON employee_embeddings(employee_id);
CREATE INDEX idx_embeddings_active        ON employee_embeddings(employee_id, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_embeddings_source        ON employee_embeddings(source, captured_at DESC);
CREATE INDEX idx_shift_patterns_employee  ON shift_patterns(employee_id);
CREATE INDEX idx_shift_patterns_day       ON shift_patterns(day_of_week, is_active);
CREATE INDEX idx_shift_instances_employee ON shift_instances(employee_id);
CREATE INDEX idx_shift_instances_sched    ON shift_instances(scheduled_start, scheduled_end);
CREATE INDEX idx_shift_instances_active   ON shift_instances(status) WHERE status = 'active';
CREATE INDEX idx_alerts_store_id          ON alerts(store_id);
CREATE INDEX idx_alerts_type              ON alerts(store_id, type, created_at DESC);
CREATE INDEX idx_alerts_unresolved        ON alerts(store_id, created_at DESC) WHERE resolved_at IS NULL;
CREATE INDEX idx_alerts_employee          ON alerts(employee_id) WHERE employee_id IS NOT NULL;

-- Domain 6
CREATE INDEX idx_calibrations_camera_config ON calibrations(camera_config_id);
-- Partial unique index: only one current calibration per camera config; non-current rows are unlimited (history).
CREATE UNIQUE INDEX IF NOT EXISTS one_current_per_camera_config
    ON calibrations(camera_config_id) WHERE is_current = TRUE;
CREATE INDEX idx_calibrations_current       ON calibrations(camera_config_id, is_current) WHERE is_current = TRUE;
CREATE INDEX idx_calibrations_status        ON calibrations(status);
CREATE INDEX idx_calibrations_method        ON calibrations(method, status);
CREATE INDEX idx_coordinate_frames_version  ON coordinate_frames(version_id, store_id);

-- Domain 7
CREATE INDEX idx_version_sync_store     ON version_sync_events(store_id, status);
CREATE INDEX idx_version_sync_scheduled ON version_sync_events(scheduled_at) WHERE status = 'pending';
CREATE INDEX idx_store_settings_store   ON store_settings(store_id);

-- Domain 8
CREATE INDEX idx_test_runs_store_id        ON test_runs(store_id);
CREATE INDEX idx_test_runs_version_id      ON test_runs(version_id);
CREATE INDEX idx_test_runs_status          ON test_runs(store_id, status);
CREATE INDEX idx_test_runs_expires         ON test_runs(expires_at) WHERE status = 'complete';
CREATE INDEX idx_test_run_cameras_run      ON test_run_cameras(test_run_id);
CREATE INDEX idx_test_run_cameras_physical ON test_run_cameras(physical_camera_id);

-- ============================================================================
-- DOMAIN 9 — Vision Pipeline
-- ============================================================================

CREATE TABLE IF NOT EXISTS tracking_history (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_id        TEXT        NOT NULL,
    local_id         UUID        NOT NULL,
    timestamp_ms     BIGINT      NOT NULL,
    floor_x          DOUBLE PRECISION,
    floor_y          DOUBLE PRECISION,
    zone_id          UUID        REFERENCES zones(id) ON DELETE SET NULL,
    bbox_confidence  REAL        NOT NULL,
    bbox_area        INTEGER     NOT NULL,
    -- Full-resolution bbox pixels (the unscaled bbox fed to the projector).
    bbox_x1          INTEGER,
    bbox_y1          INTEGER,
    bbox_x2          INTEGER,
    bbox_y2          INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tracking_history_camera_ts
    ON tracking_history(camera_id, timestamp_ms);

CREATE INDEX IF NOT EXISTS idx_tracking_history_store_ts
    ON tracking_history(store_id, timestamp_ms);


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


CREATE TABLE IF NOT EXISTS edge_agents (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id           UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE UNIQUE,
    status             TEXT        NOT NULL
                                   CHECK (status IN ('online', 'offline'))
                                   DEFAULT 'offline',
    last_heartbeat_at  TIMESTAMPTZ,
    agent_version      TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SCHEMA MIGRATIONS — Spec D: pending_activation state & camera_runtime_sessions
-- Idempotent: safe to run against both fresh and existing databases.
-- ============================================================================

-- D1: Extend store_config_versions.status to include 'pending_activation'.
-- PostgreSQL auto-names the inline CHECK as store_config_versions_status_check.
ALTER TABLE store_config_versions
    DROP CONSTRAINT IF EXISTS store_config_versions_status_check;
ALTER TABLE store_config_versions
    ADD CONSTRAINT store_config_versions_status_check
    CHECK (status IN ('draft', 'active', 'archived', 'pending_activation'));

-- D2: Scheduled activation timestamp — NULL unless status='pending_activation'.
ALTER TABLE store_config_versions
    ADD COLUMN IF NOT EXISTS activate_at TIMESTAMPTZ;

-- D3: camera_runtime_sessions — append-only camera start/stop event log.
-- FK cascade semantics: store deletion purges history (CASCADE); hardware or
-- config deletion preserves history (SET NULL).
CREATE TABLE IF NOT EXISTS camera_runtime_sessions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id            UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    physical_camera_id  UUID        REFERENCES physical_cameras(id) ON DELETE SET NULL,
    camera_config_id    UUID        REFERENCES camera_configs(id)   ON DELETE SET NULL,
    version_id          UUID        REFERENCES store_config_versions(id) ON DELETE SET NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    stopped_at          TIMESTAMPTZ,
    stop_reason         TEXT        CHECK (stop_reason IN (
                            'schedule', 'manual', 'version_activation',
                            'eep_restart', 'crash', 'unknown'
                        ))
);

-- Crash-recovery query path: find open sessions for a store.
CREATE INDEX IF NOT EXISTS idx_crs_store_open
    ON camera_runtime_sessions(store_id)
    WHERE stopped_at IS NULL;

-- Per-camera historical timeline.
CREATE INDEX IF NOT EXISTS idx_crs_camera_history
    ON camera_runtime_sessions(physical_camera_id, started_at);

-- Fix: replace the broken two-column unique constraint on calibrations with a
-- partial unique index. The original UNIQUE(camera_config_id, is_current) only
-- allowed one non-current calibration ever, breaking re-calibration workflows.
-- The correct intent is: only one is_current=TRUE per camera config; history is
-- unlimited.
ALTER TABLE calibrations
    DROP CONSTRAINT IF EXISTS one_current_per_camera_config;
DROP INDEX IF EXISTS one_current_per_camera_config;
CREATE UNIQUE INDEX IF NOT EXISTS one_current_per_camera_config
    ON calibrations(camera_config_id) WHERE is_current = TRUE;

-- ============================================================================
-- DOMAIN 9 ADDITIONS — IEP3 Reconciliation Prerequisites
-- Idempotent: safe to run against both fresh and existing databases.
-- FK dependency order: physical_cameras (no deps) → crs index → local_centroids
-- (stores) → global_identities (stores, zones) → global_local_mapping →
-- global_embeddings → global_tracking_history (global_identities, stores,
-- store_config_versions, zones).
-- ============================================================================

-- 1. Stream resolution on physical_cameras — read by IEP3 for aspect-ratio
--    normalisation during cross-camera ReID matching.
ALTER TABLE physical_cameras
    ADD COLUMN IF NOT EXISTS stream_width  INTEGER,
    ADD COLUMN IF NOT EXISTS stream_height INTEGER;

-- 2. Fast lookup of open sessions by physical camera — used by IEP3 to resolve
--    which store a camera_id belongs to at reconciliation time.
CREATE INDEX IF NOT EXISTS idx_crs_physical_open
    ON camera_runtime_sessions(physical_camera_id)
    WHERE stopped_at IS NULL;

-- 3. local_centroids — per-camera appearance embedding store per local track.
--    Written by IEP2 after each batch; read by IEP3 for cross-camera matching.
--    local_id is the same UUID derived by uuid.UUID(int=local_id) in IEP2.
--    embeddings holds up to MAX_EMBEDDINGS (10) raw float32[2048] vectors
--    concatenated (8192 bytes each); embedding_count is how many are present;
--    quality_scores holds one float32 per embedding (4 bytes each). See
--    migration 0013_embedding_store. Representative centroid is recomputed on
--    demand, never stored.
CREATE TABLE IF NOT EXISTS local_centroids (
    local_id         UUID        PRIMARY KEY,
    camera_id        TEXT        NOT NULL,
    store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    embeddings       BYTEA       NOT NULL,
    embedding_count  SMALLINT    NOT NULL DEFAULT 0,
    quality_scores   BYTEA       NOT NULL DEFAULT ''::bytea,
    updated_at_batch INT         NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_local_centroids_camera
    ON local_centroids(camera_id);

CREATE INDEX IF NOT EXISTS idx_local_centroids_store
    ON local_centroids(store_id);

-- 4. global_identities — one row per store-wide person identity.
--    Owned by IEP3. state machine: active → lost → exited.
--    All timestamps are epoch ms sourced from tracking_history.timestamp_ms.
CREATE TABLE IF NOT EXISTS global_identities (
    global_id      UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id       UUID             NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    first_seen_ts  BIGINT           NOT NULL,
    last_seen_ts   BIGINT           NOT NULL,
    last_floor_x   DOUBLE PRECISION,
    last_floor_y   DOUBLE PRECISION,
    state          VARCHAR(16)      NOT NULL DEFAULT 'active'
                   CHECK (state IN ('active', 'lost', 'exited')),
    lost_since_ts  BIGINT,
    entry_zone_id  UUID             REFERENCES zones(id) ON DELETE SET NULL,
    exit_zone_id   UUID             REFERENCES zones(id) ON DELETE SET NULL,
    -- Employee linking (specs/employee-linking). is_employee is read by IEP4's
    -- GET_DELTA; employee_id is the specific punch-in link. Both set by the EEP
    -- punch_resolver. (Migration 0013 mirrors this for existing databases.)
    is_employee    BOOLEAN          NOT NULL DEFAULT FALSE,
    employee_id    UUID             REFERENCES employees(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_global_identities_store_state
    ON global_identities(store_id, state);

CREATE INDEX IF NOT EXISTS idx_global_identities_employee
    ON global_identities(employee_id) WHERE employee_id IS NOT NULL;

-- Partial index: only index lost rows for the lost-timeout sweep query.
CREATE INDEX IF NOT EXISTS idx_global_identities_lost
    ON global_identities(state, lost_since_ts)
    WHERE state = 'lost';

-- ── Employee linking (specs/employee-linking) ────────────────────────────────
-- Defined here (after global_identities) because punch_events FK-references it.
-- Migration 0013 mirrors these for existing databases.

-- punch_in_stations — one per config version: the camera that sees the punch
-- machine and the machine's floor position (world metres) + match radius.
CREATE TABLE IF NOT EXISTS punch_in_stations (
    id               UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id       UUID             NOT NULL
                     REFERENCES store_config_versions(id) ON DELETE CASCADE,
    store_id         UUID             NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_config_id UUID             NOT NULL
                     REFERENCES camera_configs(id) ON DELETE CASCADE,
    world_x          DOUBLE PRECISION NOT NULL,
    world_y          DOUBLE PRECISION NOT NULL,
    radius_m         DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    created_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT uq_punch_station_per_version UNIQUE (version_id),
    CONSTRAINT positive_radius CHECK (radius_m > 0)
);

CREATE INDEX IF NOT EXISTS idx_punch_stations_version
    ON punch_in_stations(version_id);

-- punch_events — ingested punch-in records; resolved by the EEP punch_resolver.
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

-- 5. global_local_mapping — maps per-camera LocalIDs to GlobalIDs.
--    All timestamps are epoch ms. Partial unique index enforces one active
--    LocalID per camera per GlobalID at DB level.
CREATE TABLE IF NOT EXISTS global_local_mapping (
    id             BIGSERIAL   PRIMARY KEY,
    global_id      UUID        NOT NULL
                   REFERENCES global_identities(global_id) ON DELETE CASCADE,
    camera_id      TEXT        NOT NULL,
    local_id       UUID        NOT NULL,
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    linked_at_ts   BIGINT      NOT NULL,
    last_seen_ts   BIGINT      NOT NULL,
    unlinked_at_ts BIGINT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_glm_one_active_per_camera
    ON global_local_mapping(global_id, camera_id)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_glm_local_id
    ON global_local_mapping(local_id);

CREATE INDEX IF NOT EXISTS idx_glm_global_active
    ON global_local_mapping(global_id, is_active);

-- 6. global_embeddings — per-camera appearance embedding store per GlobalID.
--    Same packed layout as local_centroids: up to MAX_EMBEDDINGS (10) raw
--    float32[2048] vectors (8192 bytes each) in embeddings, embedding_count of
--    them, and one float32 quality score each in quality_scores. Merged from the
--    matched local_centroids heaps by IEP3 (Stage 8). See migration 0013.
CREATE TABLE IF NOT EXISTS global_embeddings (
    global_id       UUID     NOT NULL
                    REFERENCES global_identities(global_id) ON DELETE CASCADE,
    camera_id       TEXT     NOT NULL,
    embeddings      BYTEA    NOT NULL,
    embedding_count SMALLINT NOT NULL DEFAULT 0,
    quality_scores  BYTEA    NOT NULL DEFAULT ''::bytea,
    updated_at_ts   BIGINT   NOT NULL,
    PRIMARY KEY (global_id, camera_id)
);

CREATE INDEX IF NOT EXISTS idx_global_embeddings_global
    ON global_embeddings(global_id);

-- 7. global_tracking_history — canonical store-wide position per GlobalID per
--    batch. floor_x/floor_y are NOT NULL: calibration is a hard prerequisite
--    for version activation (enforced in A2). version_id and zone_id use
--    ON DELETE SET NULL to preserve history when configs are archived.
--    batch_number is correlation metadata only — not used by the state machine.
--    It carries the IEP3 coordinator's batch key, which is window_start_ms
--    rounded to the window boundary (epoch milliseconds). BIGINT is required —
--    epoch-ms values exceed INT4 range.
CREATE TABLE IF NOT EXISTS global_tracking_history (
    id              BIGSERIAL        PRIMARY KEY,
    global_id       UUID             NOT NULL
                    REFERENCES global_identities(global_id) ON DELETE CASCADE,
    store_id        UUID             NOT NULL
                    REFERENCES stores(id) ON DELETE CASCADE,
    version_id      UUID
                    REFERENCES store_config_versions(id) ON DELETE SET NULL,
    batch_number    BIGINT           NOT NULL,
    timestamp_ms    BIGINT           NOT NULL,
    floor_x         DOUBLE PRECISION NOT NULL,
    floor_y         DOUBLE PRECISION NOT NULL,
    zone_id         UUID             REFERENCES zones(id) ON DELETE SET NULL,
    source_camera   TEXT             NOT NULL,
    source_local_id UUID             NOT NULL,
    selection_score FLOAT4           NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gth_global_ts
    ON global_tracking_history(global_id, timestamp_ms);

CREATE INDEX IF NOT EXISTS idx_gth_store_ts
    ON global_tracking_history(store_id, timestamp_ms);

CREATE INDEX IF NOT EXISTS idx_gth_batch
    ON global_tracking_history(store_id, batch_number);

CREATE INDEX IF NOT EXISTS idx_gth_zone_ts
    ON global_tracking_history(zone_id, timestamp_ms)
    WHERE zone_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gth_version
    ON global_tracking_history(version_id)
    WHERE version_id IS NOT NULL;

-- ============================================================================
-- M7-S1 — Camera Intrinsics + PnP Calibration Foundation
-- Idempotent: safe to run against both fresh and existing databases.
-- ============================================================================

-- Intrinsic fields on physical_cameras. stream_width / stream_height already
-- exist from the Domain 9 migration above — do NOT re-add them.
ALTER TABLE physical_cameras
    ADD COLUMN IF NOT EXISTS lens_focal_length_mm  FLOAT,
    ADD COLUMN IF NOT EXISTS h_fov_deg             FLOAT,
    ADD COLUMN IF NOT EXISTS v_fov_deg             FLOAT,
    ADD COLUMN IF NOT EXISTS fx                    FLOAT,
    ADD COLUMN IF NOT EXISTS fy                    FLOAT,
    ADD COLUMN IF NOT EXISTS cx                    FLOAT,
    ADD COLUMN IF NOT EXISTS cy                    FLOAT,
    ADD COLUMN IF NOT EXISTS dist_coeffs           JSONB,
    ADD COLUMN IF NOT EXISTS intrinsics_source     VARCHAR(20)
                             CHECK (intrinsics_source IN ('estimated', 'chessboard'));

-- Add 'pnp' and 'tps' to the calibrations method enum.
ALTER TABLE calibrations
    DROP CONSTRAINT IF EXISTS calibrations_method_check;
ALTER TABLE calibrations
    ADD CONSTRAINT calibrations_method_check
    CHECK (method IN ('homography', 'calibration_files', 'pnp', 'tps'));
