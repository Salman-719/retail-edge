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
    access_scope VARCHAR(20) NOT NULL DEFAULT 'full_store'
                 CHECK (access_scope IN ('full_store', 'section_scoped')),
    invited_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT one_membership_per_user_per_store UNIQUE (user_id, store_id)
);

-- sections here so store_member_sections can reference it directly
CREATE TABLE sections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id      UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    name          VARCHAR(255) NOT NULL,
    type          VARCHAR(30) NOT NULL DEFAULT 'floor'
                  CHECK (type IN ('floor', 'wing', 'outdoor', 'warehouse', 'other')),
    display_order INTEGER NOT NULL DEFAULT 0,
    is_default    BOOLEAN NOT NULL DEFAULT FALSE,
    status        VARCHAR(20) NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'inactive')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT one_default_section_per_store
        UNIQUE (store_id, is_default)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE store_member_sections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_member_id UUID NOT NULL REFERENCES store_members(id) ON DELETE CASCADE,
    section_id      UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    CONSTRAINT unique_member_section UNIQUE (store_member_id, section_id)
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
    access_scope  VARCHAR(20) NOT NULL DEFAULT 'full_store'
                  CHECK (access_scope IN ('full_store', 'section_scoped')),
    section_ids   JSONB NOT NULL DEFAULT '[]',
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
    action       VARCHAR(50) NOT NULL CHECK (action IN (
                     'login', 'logout',
                     'config_edited', 'version_activated', 'version_rolled_back',
                     'member_invited', 'member_removed', 'member_role_changed',
                     'permission_changed', 'password_reset',
                     'employee_created', 'employee_updated', 'employee_deleted',
                     'shift_created', 'shift_updated', 'shift_deleted',
                     'store_created', 'store_updated',
                     'draft_created', 'draft_discarded', 'draft_expired'
                 )),
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
    section_id         UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    version_id         UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    origin_description TEXT,
    x_axis_description TEXT,
    units              VARCHAR(20) NOT NULL DEFAULT 'meters',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_frame_per_section_version UNIQUE (section_id, version_id)
);

-- ============================================================================
-- DOMAIN 3 — Floor Plan & Spatial
-- ============================================================================

-- floor_plans: includes coordinate_frame_id (Domain 6)
CREATE TABLE floor_plans (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id          UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    section_id          UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
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
    CONSTRAINT unique_floor_plan_per_section_version UNIQUE (version_id, section_id),
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
    section_id              UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
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
    CONSTRAINT zone_name_unique_per_section_version UNIQUE (version_id, section_id, name)
);

CREATE TABLE obstacles (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    section_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
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
    section_id          UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
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
    last_seen_section_id UUID REFERENCES sections(id) ON DELETE SET NULL,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_employee_code_per_store
        UNIQUE (store_id, employee_code)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE employee_sections (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    section_id  UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_employee_section UNIQUE (employee_id, section_id)
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
    section_id         UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
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
    section_id         UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
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
    section_id  UUID REFERENCES sections(id) ON DELETE SET NULL,
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

    CONSTRAINT one_current_per_camera_config
        UNIQUE (camera_config_id, is_current)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT verified_requires_computation
        CHECK (
            status != 'verified' OR
            rms_reprojection_error IS NOT NULL OR
            intrinsic_matrix IS NOT NULL
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
CREATE INDEX idx_member_sections_member ON store_member_sections(store_member_id);
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
CREATE INDEX idx_sections_store_id    ON sections(store_id);
CREATE INDEX idx_sections_status      ON sections(store_id, status);
CREATE INDEX idx_versions_store_id    ON store_config_versions(store_id);
CREATE INDEX idx_versions_status      ON store_config_versions(store_id, status);
CREATE INDEX idx_versions_active_from ON store_config_versions(active_from DESC);
CREATE INDEX idx_versions_expires_at  ON store_config_versions(expires_at)
    WHERE status = 'draft';

-- Domain 3
CREATE INDEX idx_floor_plans_version_id ON floor_plans(version_id);
CREATE INDEX idx_floor_plans_section_id ON floor_plans(section_id);
CREATE INDEX idx_zones_version_id       ON zones(version_id);
CREATE INDEX idx_zones_section_id       ON zones(section_id);
CREATE INDEX idx_zones_type             ON zones(version_id, type);
CREATE INDEX idx_obstacles_version_id   ON obstacles(version_id);
CREATE INDEX idx_obstacles_section_id   ON obstacles(section_id);

-- Domain 4
CREATE INDEX idx_physical_cameras_store_id   ON physical_cameras(store_id);
CREATE INDEX idx_physical_cameras_active     ON physical_cameras(store_id, is_active);
CREATE INDEX idx_physical_cameras_health     ON physical_cameras(health_status);
CREATE INDEX idx_camera_configs_version_id   ON camera_configs(version_id);
CREATE INDEX idx_camera_configs_physical_id  ON camera_configs(physical_camera_id);
CREATE INDEX idx_camera_configs_section_id   ON camera_configs(section_id);
CREATE INDEX idx_camera_configs_status       ON camera_configs(version_id, status);
CREATE INDEX idx_camera_zone_coverage_camera ON camera_zone_coverage(camera_config_id);
CREATE INDEX idx_camera_zone_coverage_zone   ON camera_zone_coverage(zone_id);

-- Domain 5
CREATE INDEX idx_employees_store_id       ON employees(store_id);
CREATE INDEX idx_employees_active         ON employees(store_id, is_active);
CREATE INDEX idx_employees_on_shift       ON employees(store_id, is_on_shift) WHERE is_on_shift = TRUE;
CREATE INDEX idx_employee_sections_emp    ON employee_sections(employee_id);
CREATE INDEX idx_employee_sections_sec    ON employee_sections(section_id);
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
CREATE INDEX idx_calibrations_current       ON calibrations(camera_config_id, is_current) WHERE is_current = TRUE;
CREATE INDEX idx_calibrations_status        ON calibrations(status);
CREATE INDEX idx_calibrations_method        ON calibrations(method, status);
CREATE INDEX idx_coordinate_frames_section  ON coordinate_frames(section_id, version_id);

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
-- Domain 9 — IEP2 Vision (per-camera local identity) + IEP3 Reconciliation
--            (cross-camera global identity)
--
-- These tables are owned by the IEP2/IEP3 subsystem and mirrored by the
-- SQLAlchemy models in common/models/{iep2_tables,iep3_tables,shared_tables}.py.
-- IEP2 writes tracking_history / local_embeddings / local_centroids; IEP3 reads
-- tracking_history + local_centroids (read-only) and owns the global_* tables.
-- ============================================================================

-- IEP2: per-camera floor positions (2s buffered writes; read by IEP3 per batch)
CREATE TABLE tracking_history (
    id              BIGSERIAL PRIMARY KEY,
    local_id        UUID    NOT NULL,
    camera_id       VARCHAR(64) NOT NULL,
    timestamp_ms    BIGINT  NOT NULL,
    floor_x         FLOAT   NOT NULL,
    floor_y         FLOAT   NOT NULL,
    zone_id         VARCHAR(64),
    bbox_confidence FLOAT,
    bbox_area       FLOAT,
    bbox_x1         FLOAT,
    bbox_y1         FLOAT,
    bbox_x2         FLOAT,
    bbox_y2         FLOAT
);

-- IEP2: persistent per-LocalID embedding store (crash recovery + audit)
CREATE TABLE local_embeddings (
    local_id        UUID    NOT NULL,
    captured_ts     BIGINT  NOT NULL,
    camera_id       VARCHAR(64) NOT NULL,
    embedding       BYTEA   NOT NULL,   -- float32[D] tobytes()
    yolo_confidence FLOAT   NOT NULL,
    is_init         BOOLEAN NOT NULL,
    PRIMARY KEY (local_id, captured_ts)
);

-- IEP2: current centroid per LocalID (primary ReID interface for IEP3)
CREATE TABLE local_centroids (
    local_id         UUID    PRIMARY KEY,
    camera_id        VARCHAR(64) NOT NULL,
    centroid         BYTEA   NOT NULL,  -- float32[D] tobytes()
    updated_at_batch INTEGER NOT NULL
);

-- IEP3: authoritative registry of store-wide identities
CREATE TABLE global_identities (
    global_id        UUID    PRIMARY KEY,
    store_id         UUID    NOT NULL,
    first_seen_ts    BIGINT  NOT NULL,
    last_seen_ts     BIGINT  NOT NULL,
    state            VARCHAR(16) NOT NULL,
    lost_since_batch INTEGER,
    last_floor_x     FLOAT,
    last_floor_y     FLOAT,
    CONSTRAINT state_valid CHECK (state IN ('active','lost','exited'))
);

-- IEP3: LocalID -> GlobalID linkage with full history
CREATE TABLE global_local_mapping (
    id                BIGSERIAL PRIMARY KEY,
    global_id         UUID    NOT NULL REFERENCES global_identities(global_id),
    camera_id         VARCHAR(64) NOT NULL,
    local_id          UUID    NOT NULL,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    linked_at_batch   INTEGER NOT NULL,
    last_seen_batch   INTEGER NOT NULL,
    unlinked_at_batch INTEGER
);

-- IEP3: per-camera centroid for each GlobalID (cross-camera ReID)
CREATE TABLE global_embeddings (
    global_id        UUID    NOT NULL REFERENCES global_identities(global_id),
    camera_id        VARCHAR(64) NOT NULL,
    centroid         BYTEA   NOT NULL,
    updated_at_batch INTEGER NOT NULL,
    PRIMARY KEY (global_id, camera_id)
);

-- IEP3: diverse gallery samples per GlobalID for max-similarity ReID
CREATE TABLE global_gallery_embeddings (
    id               BIGSERIAL PRIMARY KEY,
    global_id        UUID    NOT NULL REFERENCES global_identities(global_id),
    camera_id        VARCHAR(64) NOT NULL,
    source_local_id  UUID    NOT NULL,
    embedding        BYTEA   NOT NULL,
    updated_at_batch INTEGER NOT NULL
);

-- IEP3: canonical store-wide position log (one row per GlobalID per batch)
CREATE TABLE global_tracking_history (
    id              BIGSERIAL PRIMARY KEY,
    global_id       UUID    NOT NULL REFERENCES global_identities(global_id),
    store_id        UUID    NOT NULL,
    batch_number    INTEGER NOT NULL,
    timestamp_ms    BIGINT  NOT NULL,
    floor_x         FLOAT   NOT NULL,
    floor_y         FLOAT   NOT NULL,
    zone_id         VARCHAR(64),
    source_camera   VARCHAR(64) NOT NULL,
    source_local_id UUID    NOT NULL,
    selection_score FLOAT   NOT NULL
);

-- Demo/seed calibration table (production IEP2 reads calibrations/zones instead)
CREATE TABLE camera_calibrations (
    cam_id        VARCHAR(64) PRIMARY KEY,
    store_id      UUID  NOT NULL,
    homography    DOUBLE PRECISION[] NOT NULL,  -- 9 elements, 3x3 row-major (validated in app)
    zone_polygons JSONB NOT NULL
);

-- Domain 9 indexes
CREATE INDEX ix_tracking_history_local_id_ts ON tracking_history(local_id, timestamp_ms);
CREATE INDEX ix_tracking_history_ts          ON tracking_history(timestamp_ms);
CREATE INDEX ix_tracking_history_camera_ts   ON tracking_history(camera_id, timestamp_ms);
CREATE INDEX ix_local_embeddings_local_id    ON local_embeddings(local_id);
CREATE INDEX ix_local_embeddings_camera_ts   ON local_embeddings(camera_id, captured_ts);
CREATE INDEX ix_local_centroids_camera_id    ON local_centroids(camera_id);
CREATE INDEX ix_global_identities_store_state ON global_identities(store_id, state);
CREATE INDEX ix_global_identities_state_lost  ON global_identities(state, lost_since_batch);
-- Only one ACTIVE LocalID per camera per GlobalID (partial unique index)
CREATE UNIQUE INDEX uq_glm_global_camera_active ON global_local_mapping(global_id, camera_id)
    WHERE is_active = TRUE;
CREATE INDEX ix_global_local_mapping_local_id     ON global_local_mapping(local_id);
CREATE INDEX ix_global_local_mapping_global_active ON global_local_mapping(global_id, is_active);
CREATE INDEX ix_global_embeddings_global_id  ON global_embeddings(global_id);
CREATE INDEX ix_global_gallery_embeddings_global_id ON global_gallery_embeddings(global_id);
CREATE INDEX ix_global_gallery_embeddings_camera_id ON global_gallery_embeddings(camera_id);
CREATE INDEX ix_gth_global_ts ON global_tracking_history(global_id, timestamp_ms);
CREATE INDEX ix_gth_store_ts  ON global_tracking_history(store_id, timestamp_ms);
CREATE INDEX ix_gth_batch     ON global_tracking_history(batch_number);
CREATE INDEX ix_gth_zone_ts   ON global_tracking_history(zone_id, timestamp_ms);
CREATE INDEX ix_camera_calibrations_store ON camera_calibrations(store_id);
