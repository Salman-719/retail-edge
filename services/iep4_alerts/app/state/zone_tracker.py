"""Zone transition detection + zone_transition_log writes.

A transition is recorded when a person's current_zone_id changed between the
previous cycle's in-memory state and this cycle's. Only the EXITED (previous)
zone produces a closed row; the new zone's session stays open in
active_person_state until the next change. exited_at_ms must be strictly
greater than entered_at_ms (DB CHECK positive_dwell).
"""
from __future__ import annotations

import uuid

from app.models import PersonState, ZoneTransition


def detect_transitions(
    prev_states: dict[uuid.UUID, PersonState],
    new_states: dict[uuid.UUID, PersonState],
) -> list[ZoneTransition]:
    transitions: list[ZoneTransition] = []
    for gid, new in new_states.items():
        prev = prev_states.get(gid)
        if prev is None:
            continue
        if prev.current_zone_id == new.current_zone_id:
            continue
        if prev.current_zone_id is None:
            continue  # was not in any zone — nothing to close
        entered = prev.entered_current_zone_at
        exited = new.last_seen_at
        if entered is None or exited <= entered:
            continue  # respect CHECK (exited_at_ms > entered_at_ms)
        transitions.append(ZoneTransition(
            global_id=gid,
            zone_id=prev.current_zone_id,
            entered_at_ms=entered,
            exited_at_ms=exited,
            is_employee=new.is_employee,
            entry_batch=prev.entered_zone_batch if prev.entered_zone_batch is not None else prev.last_batch_number,
            exit_batch=new.last_batch_number,
        ))
    return transitions


class ZoneTracker:
    """Detects transitions and appends them to zone_transition_log."""

    def __init__(self, repo) -> None:
        self._repo = repo

    async def process(
        self,
        prev_states: dict[uuid.UUID, PersonState],
        new_states: dict[uuid.UUID, PersonState],
    ) -> int:
        transitions = detect_transitions(prev_states, new_states)
        await self._repo.insert_zone_transitions(transitions)
        return len(transitions)
