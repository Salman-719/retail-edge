"""Visit session open/close.

A visit opens when a global_id first appears in active_person_state and closes
when the person is removed because global_identities.state is LOST or EXITED.
On close, zones_visited / entry_zone_id / exit_zone_id are derived from the
zone_transition_log rows recorded since the visit opened (handled in SQL).
"""
from __future__ import annotations

import uuid

from app.models import PersonState


class VisitTracker:
    def __init__(self, repo, version_id: uuid.UUID | None) -> None:
        self._repo = repo
        self._version_id = version_id

    def set_version(self, version_id: uuid.UUID | None) -> None:
        self._version_id = version_id

    async def open_new(
        self,
        new_global_ids: list[uuid.UUID],
        states: dict[uuid.UUID, PersonState],
        first_seen: dict[uuid.UUID, int],
    ) -> int:
        opened = 0
        for gid in new_global_ids:
            st = states.get(gid)
            if st is None:
                continue
            entered_at = first_seen.get(gid, st.last_seen_at)
            await self._repo.open_visit(
                global_id=gid,
                entered_at_ms=entered_at,
                is_employee=st.is_employee,
                version_id=self._version_id,
            )
            opened += 1
        return opened

    async def close(self, global_id: uuid.UUID, exited_at_ms: int) -> None:
        await self._repo.close_visit(global_id, exited_at_ms)
