"""active_person_state — compute per-person state from the delta and bulk upsert.

The current zone is the zone of a person's latest observation in the delta.
entered_current_zone_at is carried over from the previous in-memory state when
the zone is unchanged (continuous dwell), or reset to the time the person
entered the new zone within this delta when it changed.
"""
from __future__ import annotations

import uuid
from collections import OrderedDict

from app.models import DeltaRow, PersonState


def group_by_global(delta: list[DeltaRow]) -> "OrderedDict[uuid.UUID, list[DeltaRow]]":
    """Delta is ordered by (global_id, timestamp_ms ASC). Preserve that order."""
    groups: "OrderedDict[uuid.UUID, list[DeltaRow]]" = OrderedDict()
    for r in delta:
        groups.setdefault(r.global_id, []).append(r)
    return groups


def first_seen_map(delta: list[DeltaRow]) -> dict[uuid.UUID, int]:
    """Earliest timestamp_ms per global_id in this delta (visit entry time)."""
    out: dict[uuid.UUID, int] = {}
    for r in delta:
        if r.global_id not in out or r.timestamp_ms < out[r.global_id]:
            out[r.global_id] = r.timestamp_ms
    return out


def compute_states(
    delta: list[DeltaRow],
    prev_states: dict[uuid.UUID, PersonState],
) -> dict[uuid.UUID, PersonState]:
    """Build the new in-memory PersonState for every global_id in the delta."""
    states: dict[uuid.UUID, PersonState] = {}
    for gid, rows in group_by_global(delta).items():
        last = rows[-1]
        current_zone = last.zone_id

        # Earliest timestamp/batch of the trailing run still in the current zone.
        entry_ts = last.timestamp_ms
        entry_batch = last.batch_number
        for r in reversed(rows):
            if r.zone_id == current_zone:
                entry_ts = r.timestamp_ms
                entry_batch = r.batch_number
            else:
                break

        prev = prev_states.get(gid)
        if prev is not None and prev.current_zone_id == current_zone:
            entered_at = prev.entered_current_zone_at if prev.entered_current_zone_at is not None else entry_ts
            entered_batch = prev.entered_zone_batch if prev.entered_zone_batch is not None else entry_batch
        else:
            entered_at = entry_ts
            entered_batch = entry_batch

        states[gid] = PersonState(
            global_id=gid,
            current_zone_id=current_zone,
            entered_current_zone_at=entered_at,
            last_seen_at=last.timestamp_ms,
            last_batch_number=last.batch_number,
            is_employee=last.is_employee,
            employee_id=last.employee_id,
            entered_zone_batch=entered_batch,
        )
    return states


class PersonStateManager:
    """Owns active_person_state writes (bulk upsert / delete)."""

    def __init__(self, repo) -> None:
        self._repo = repo

    async def persist(self, states: dict[uuid.UUID, PersonState]) -> None:
        rows = [
            (
                s.global_id,
                s.current_zone_id,
                s.entered_current_zone_at,
                s.last_seen_at,
                s.last_batch_number,
                s.is_employee,
                s.employee_id,
            )
            for s in states.values()
        ]
        await self._repo.upsert_active_person_state(rows)

    async def delete(self, global_ids: list[uuid.UUID]) -> None:
        await self._repo.delete_active_person_state(global_ids)
