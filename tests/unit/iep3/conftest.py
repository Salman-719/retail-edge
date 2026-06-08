"""
Shared fixtures for IEP3 unit tests.
Adds IEP3 app to sys.path so imports resolve without pip install.
"""
import sys
import os
import uuid
import numpy as np
import pytest

# Make IEP3 app importable
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "services", "iep3_reconciliation"),
)

from app.repository import (
    LocalObservation, GlobalCandidate, PositionRow,
    MappingRow, ResolutionResult, CameraBatchInfo,
)
from app.settings import Iep3Settings


# ── Reusable IDs ─────────────────────────────────────────────────────────────

STORE_ID  = str(uuid.UUID(int=1))
CAM_01    = str(uuid.UUID(int=10))
CAM_02    = str(uuid.UUID(int=11))
CAM_03    = str(uuid.UUID(int=12))
LOCAL_01  = uuid.UUID(int=101)
LOCAL_02  = uuid.UUID(int=102)
LOCAL_03  = uuid.UUID(int=103)
GLOBAL_01 = uuid.UUID(int=1001)
GLOBAL_02 = uuid.UUID(int=1002)

WINDOW_START = 1_700_000_000_000
WINDOW_END   = 1_700_000_060_000


# ── Standard centroids ────────────────────────────────────────────────────────

def unit_vec(dim: int = 2048) -> np.ndarray:
    """Return an L2-normalized all-ones vector."""
    v = np.ones(dim, dtype=np.float32)
    return v / np.linalg.norm(v)


def orthogonal_vec(dim: int = 2048) -> np.ndarray:
    """Return a vector orthogonal to unit_vec (only first element differs)."""
    v = np.zeros(dim, dtype=np.float32)
    v[0] = 1.0
    return v


# ── Default settings ──────────────────────────────────────────────────────────

@pytest.fixture
def settings() -> Iep3Settings:
    return Iep3Settings(
        store_id=STORE_ID,
        window_seconds=60.0,
        database_url_server="postgresql://test:test@localhost/test",
        server_redis_url="redis://localhost:6379/0",
        expected_cameras=2,
        coordinator_timeout_s=120.0,
        reid_threshold=0.85,
        max_speed_mps=1.5,
        embedding_dim=2048,
        position_weight_area=0.7,
        position_weight_conf=0.3,
        grace_seconds=300.0,
        default_frame_width=1920,
        default_frame_height=1080,
    )


# ── LocalObservation helpers ──────────────────────────────────────────────────

def make_obs(
    local_id=LOCAL_01,
    camera_id=CAM_01,
    floor_x=5.0,
    floor_y=3.0,
    last_seen_ts=WINDOW_START + 30_000,
    first_seen_ts=WINDOW_START + 10_000,
    confidence=0.9,
    bbox_area=5000.0,
) -> LocalObservation:
    return LocalObservation(
        local_id=local_id,
        camera_id=camera_id,
        last_floor_x=floor_x,
        last_floor_y=floor_y,
        last_seen_ts=last_seen_ts,
        first_seen_ts=first_seen_ts,
        best_confidence=confidence,
        best_bbox_area=bbox_area,
    )


def make_pos(
    global_id=GLOBAL_01,
    local_id=LOCAL_01,
    camera_id=CAM_01,
    floor_x=5.0,
    floor_y=3.0,
    zone_id=None,
    timestamp_ms=WINDOW_START + 30_000,
    bbox_confidence=0.9,
    bbox_area=5000.0,
    needs_entry_zone=True,
) -> PositionRow:
    return PositionRow(
        global_id=global_id,
        local_id=local_id,
        camera_id=camera_id,
        floor_x=floor_x,
        floor_y=floor_y,
        zone_id=zone_id,
        timestamp_ms=timestamp_ms,
        bbox_confidence=bbox_confidence,
        bbox_area=bbox_area,
        needs_entry_zone=needs_entry_zone,
    )
