"""Foundation tests for the ORM model definitions.

These assert at the metadata level (no DB required) that the subsystem
tables exist with the constraints the specs mandate -- in particular the partial
unique index on global_local_mapping and the state check constraint. A real
create_all against Postgres is exercised separately in the verification step.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint

from common.models import Base


EXPECTED_TABLES = {
    "tracking_history",
    "local_embeddings",
    "local_centroids",
    "global_identities",
    "global_local_mapping",
    "global_embeddings",
    "global_gallery_embeddings",
    "global_tracking_history",
    "camera_calibrations",
}


def test_all_subsystem_tables_defined():
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_global_local_mapping_has_partial_unique_index():
    table = Base.metadata.tables["global_local_mapping"]
    idx = next(i for i in table.indexes if i.name == "uq_glm_global_camera_active")
    assert idx.unique is True
    # dialect-specific predicate present so it is a PARTIAL unique index
    assert idx.dialect_options["postgresql"]["where"] is not None
    assert {c.name for c in idx.columns} == {"global_id", "camera_id"}


def test_global_identities_state_check_constraint():
    table = Base.metadata.tables["global_identities"]
    checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    assert any("state" in str(c.sqltext).lower() for c in checks)


def test_global_identities_has_last_floor_columns():
    table = Base.metadata.tables["global_identities"]
    assert "last_floor_x" in table.columns
    assert "last_floor_y" in table.columns
