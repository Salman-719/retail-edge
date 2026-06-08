"""Employee linking: global_id <-> employee_id punch-in flow.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-08

(Renumbered 0013 -> 0014 during the employee-detection merge: 0013 was already
taken by 0013_embedding_store on this branch. Chains after it; the two are
independent — embedding store touches local_centroids/global_embeddings, this
touches global_identities/punch tables.)

Adds the schema for the punch-in-anchored employee linking flow (specs/employee-linking):

  1. global_identities gains `is_employee` + `employee_id`. NOTE: IEP4's GET_DELTA already
     selects `gi.is_employee`, but no prior migration ever added the column (it is also
     absent from schema.sql's global_identities CREATE TABLE). This migration repairs that
     latent dependency in addition to introducing `employee_id`.
  2. punch_in_stations — one per config version: the camera that sees the punch machine and
     the machine's floor position (world metres) + match radius. Flows through draft ->
     activate like zones/camera_configs (keyed by version_id).
  3. punch_events — ingested punch-in records; resolved by the EEP punch_resolver into a
     global_id link.
  4. active_person_state gains `employee_id` so IEP4 live state knows which employee, not
     just that one is present. (active_person_state was created in 0010 and is migration-only.)

Idempotent throughout (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS). Forward-only.
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. global_identities link columns (also repairs IEP4's is_employee dep) ──
    op.execute(
        """
        ALTER TABLE global_identities
            ADD COLUMN IF NOT EXISTS is_employee BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS employee_id UUID
                REFERENCES employees(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS idx_global_identities_employee
            ON global_identities(employee_id) WHERE employee_id IS NOT NULL;
        """
    )

    # ── 2. punch_in_stations (one per config version) ────────────────────────
    op.execute(
        """
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
        """
    )

    # ── 3. punch_events ──────────────────────────────────────────────────────
    op.execute(
        """
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
        """
    )

    # ── 4. active_person_state.employee_id (table created in 0010) ───────────
    op.execute(
        """
        ALTER TABLE active_person_state
            ADD COLUMN IF NOT EXISTS employee_id UUID
                REFERENCES employees(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS idx_aps_store_employee_id
            ON active_person_state(store_id, employee_id) WHERE employee_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    # Forward-only, consistent with 0010. Tearing down the linking columns/tables
    # would orphan IEP4's is_employee dependency.
    raise NotImplementedError("0013_employee_linking is forward-only.")
