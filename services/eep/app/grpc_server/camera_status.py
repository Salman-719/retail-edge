"""In-memory store for IEP1 container status reports received from edge agents.

Updated by the gRPC servicer on every CameraStatusReport (every 30 s per camera).
Read by REST endpoints and future alert logic.

Keys are (store_id, camera_id) where camera_id is the physical_camera UUID string.
The timestamp_ms field lets callers determine staleness independently.
"""
from __future__ import annotations

_statuses: dict[tuple[str, str], dict] = {}


def update(store_id: str, camera_id: str, status: str, timestamp_ms: int) -> None:
    _statuses[(store_id, camera_id)] = {"status": status, "timestamp_ms": timestamp_ms}


def get_for_store(store_id: str) -> dict[str, dict]:
    """Return {camera_id: {status, timestamp_ms}} for every camera in the store."""
    return {
        cam_id: data
        for (s_id, cam_id), data in _statuses.items()
        if s_id == store_id
    }


def get(store_id: str, camera_id: str) -> dict | None:
    """Return {status, timestamp_ms} for a single camera, or None if never reported."""
    return _statuses.get((store_id, camera_id))
