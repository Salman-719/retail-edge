"""Remove the sections layer entirely (SPEC-00A, Part A).

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-08

Sections were an unnecessary indirection between a store and its spatial data.
This migration eliminates the concept: drop the sections table and every
section_id FK, re-anchoring floor_plans / zones / camera_configs / obstacles /
coordinate_frames directly on store_id (the config-versioning anchor,
version_id, is retained).

Pure DDL — the dev database is empty (postgres volume was wiped in SPEC-000),
so ADD COLUMN ... NOT NULL is safe and no data backfill is required.

Deviations from the SPEC-00A draft (the draft was written against an
out-of-date schema picture):
  * Numbered 0009, not 0005 — 0005 is taken (embedding_dim_2048) and the chain
    head was 0008. Path is alembic/versions/, not db_migrations/versions/
    (db_migrations/ only exists inside the EEP image).
  * invitations.access_scope and invitations.section_ids are ALSO dropped.
    The draft only mentioned store_members.access_scope, but the invitation
    flow carries the same section-scoping fields and would otherwise reference
    a dead concept and fail the "no section columns" verification.
  * alerts.section_id is ALSO dropped (alerts already carries zone_id, so the
    section FK is redundant). Required to satisfy the spec's own check that no
    section_id column survives anywhere.
  * idx_camera_configs_section_id and idx_coordinate_frames_section are ALSO
    dropped — the draft's Step 12 list omitted them.

Runs under AUTOCOMMIT (see env.py) directly against postgres:5432.
Destructive and one-directional; downgrade is intentionally unsupported.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Step 12 (early): drop stale section-based indexes ────────────────────
    # Done first so later DROP COLUMN/TABLE statements don't trip over them.
    op.execute(
        """
        DROP INDEX IF EXISTS idx_sections_store_id;
        DROP INDEX IF EXISTS idx_sections_status;
        DROP INDEX IF EXISTS idx_floor_plans_section_id;
        DROP INDEX IF EXISTS idx_zones_section_id;
        DROP INDEX IF EXISTS idx_obstacles_section_id;
        DROP INDEX IF EXISTS idx_camera_configs_section_id;
        DROP INDEX IF EXISTS idx_coordinate_frames_section;
        DROP INDEX IF EXISTS idx_member_sections_member;
        DROP INDEX IF EXISTS idx_employee_sections_emp;
        DROP INDEX IF EXISTS idx_employee_sections_sec;
        """
    )

    # ── Step 1: drop junction tables that reference sections ─────────────────
    op.execute(
        """
        DROP TABLE IF EXISTS store_member_sections CASCADE;
        DROP TABLE IF EXISTS employee_sections CASCADE;
        """
    )

    # ── Steps 2-3: remove section FK from shift tables ───────────────────────
    op.execute("ALTER TABLE shift_patterns DROP COLUMN IF EXISTS section_id;")
    op.execute("ALTER TABLE shift_instances DROP COLUMN IF EXISTS section_id;")

    # ── Step 4: employees — drop section FK, add last_seen_zone_id ───────────
    op.execute(
        """
        ALTER TABLE employees DROP COLUMN IF EXISTS last_seen_section_id;
        ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS last_seen_zone_id UUID
            REFERENCES zones(id) ON DELETE SET NULL;
        """
    )

    # ── Step 5: store_members — drop access_scope (inline CHECK goes with it) ─
    op.execute("ALTER TABLE store_members DROP COLUMN IF EXISTS access_scope;")

    # ── Step 5b (deviation): invitations — drop section-scoping fields ───────
    op.execute(
        """
        ALTER TABLE invitations DROP COLUMN IF EXISTS access_scope;
        ALTER TABLE invitations DROP COLUMN IF EXISTS section_ids;
        """
    )

    # ── Step 6: floor_plans — section_id → store_id ──────────────────────────
    op.execute(
        """
        ALTER TABLE floor_plans
            DROP CONSTRAINT IF EXISTS unique_floor_plan_per_section_version;
        ALTER TABLE floor_plans DROP COLUMN IF EXISTS section_id;
        ALTER TABLE floor_plans
            ADD COLUMN IF NOT EXISTS store_id UUID
            NOT NULL REFERENCES stores(id) ON DELETE CASCADE;
        -- DROP-then-ADD keeps this idempotent: schema.sql (fresh init) already
        -- creates the new constraint, so a bare ADD CONSTRAINT would error.
        ALTER TABLE floor_plans
            DROP CONSTRAINT IF EXISTS unique_floor_plan_per_version;
        ALTER TABLE floor_plans
            ADD CONSTRAINT unique_floor_plan_per_version
            UNIQUE (version_id, store_id);
        """
    )

    # ── Step 7: zones — section_id → store_id ────────────────────────────────
    op.execute(
        """
        ALTER TABLE zones
            DROP CONSTRAINT IF EXISTS zone_name_unique_per_section_version;
        ALTER TABLE zones DROP COLUMN IF EXISTS section_id;
        ALTER TABLE zones
            ADD COLUMN IF NOT EXISTS store_id UUID
            NOT NULL REFERENCES stores(id) ON DELETE CASCADE;
        ALTER TABLE zones
            DROP CONSTRAINT IF EXISTS zone_name_unique_per_version;
        ALTER TABLE zones
            ADD CONSTRAINT zone_name_unique_per_version
            UNIQUE (version_id, store_id, name);
        """
    )

    # ── Step 8: camera_configs — section_id → store_id ───────────────────────
    op.execute(
        """
        ALTER TABLE camera_configs DROP COLUMN IF EXISTS section_id;
        ALTER TABLE camera_configs
            ADD COLUMN IF NOT EXISTS store_id UUID
            NOT NULL REFERENCES stores(id) ON DELETE CASCADE;
        """
    )

    # ── Step 9: obstacles — section_id → store_id ────────────────────────────
    op.execute(
        """
        ALTER TABLE obstacles DROP COLUMN IF EXISTS section_id;
        ALTER TABLE obstacles
            ADD COLUMN IF NOT EXISTS store_id UUID
            NOT NULL REFERENCES stores(id) ON DELETE CASCADE;
        """
    )

    # ── Step 10: coordinate_frames — section_id → store_id ───────────────────
    op.execute(
        """
        ALTER TABLE coordinate_frames
            DROP CONSTRAINT IF EXISTS unique_frame_per_section_version;
        ALTER TABLE coordinate_frames DROP COLUMN IF EXISTS section_id;
        ALTER TABLE coordinate_frames
            ADD COLUMN IF NOT EXISTS store_id UUID
            NOT NULL REFERENCES stores(id) ON DELETE CASCADE;
        ALTER TABLE coordinate_frames
            DROP CONSTRAINT IF EXISTS unique_frame_per_version;
        ALTER TABLE coordinate_frames
            ADD CONSTRAINT unique_frame_per_version
            UNIQUE (version_id, store_id);
        """
    )

    # ── Step 4b (deviation): alerts — drop redundant section FK ──────────────
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS section_id;")

    # ── Step 11: drop the sections table last ────────────────────────────────
    op.execute("DROP TABLE IF EXISTS sections CASCADE;")

    # ── Step 12 (rest): add new store-based indexes ──────────────────────────
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_floor_plans_store_id
            ON floor_plans(store_id);
        CREATE INDEX IF NOT EXISTS idx_zones_store_id
            ON zones(store_id);
        CREATE INDEX IF NOT EXISTS idx_camera_configs_store_id
            ON camera_configs(store_id);
        CREATE INDEX IF NOT EXISTS idx_obstacles_store_id
            ON obstacles(store_id);
        CREATE INDEX IF NOT EXISTS idx_employees_last_zone
            ON employees(last_seen_zone_id)
            WHERE last_seen_zone_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_coordinate_frames_version
            ON coordinate_frames(version_id, store_id);
        """
    )


def downgrade() -> None:
    # Hard, one-directional removal. Recreating the sections layer is out of
    # scope and would require restoring every dropped FK and junction table.
    raise NotImplementedError(
        "0009_remove_sections is irreversible — sections are removed permanently."
    )
