"""Process 1 -- ReID matcher (IEP3 spec §4).

New Local IDs are processed in ``first_seen_ts`` order so simultaneous
multi-camera appearances resolve to one Global ID within the batch. Matching is
cross-camera only: a candidate GlobalID that already maps the observation's
camera is skipped (same-camera identity is IEP2's job).

The cross-camera gate uses each candidate GlobalID's last known floor position
(``last_floor_x/y`` on the row, kept current as positions are linked this batch
and canonically by Process 2), resolving the spec's simplified pseudocode.
"""

from __future__ import annotations

import numpy as np

from common.utils.embeddings import cosine_similarity, l2_normalize
from services.iep3_reconciliation.app.reid.gates import cross_camera_gate


class ReidMatcher:
    def __init__(self, repo, settings):
        self._repo, self._s = repo, settings

    async def link_new_locals(self, session, store_id, new_obs: list, batch: int) -> None:
        for obs in sorted(new_obs, key=lambda o: o.first_seen_ts):
            await self._resolve_one(session, store_id, obs, batch)

    async def _resolve_one(self, session, store_id, obs, batch) -> None:
        new_centroid = await self._repo.load_local_centroid(session, obs.local_id)
        if new_centroid is None:
            return  # no embedding yet; skip this batch

        candidates = await self._repo.candidate_globals(session, store_id, states=("active", "lost"))

        survivors = []
        for g, cam_centroids in candidates:
            if obs.camera_id in cam_centroids:
                continue  # cross-camera only (spec invariant)
            if not self._gate_ok(obs, g):
                continue
            rep = l2_normalize(np.mean(list(cam_centroids.values()), axis=0))
            survivors.append((g, cosine_similarity(new_centroid, rep)))

        above = [(g, s) for g, s in survivors if s >= self._s.reid_match_threshold]
        if not above:
            gid = await self._repo.create_global(
                session, store_id, obs.first_seen_ts, obs.last_seen_ts, obs.last_floor_x, obs.last_floor_y
            )
            await self._repo.link(session, gid, obs.camera_id, obs.local_id, batch)
            await self._repo.upsert_global_centroid(session, gid, obs.camera_id, new_centroid, batch)
            return

        best_g, _ = max(above, key=lambda x: x[1])
        await self._repo.link(session, best_g.global_id, obs.camera_id, obs.local_id, batch)
        await self._repo.upsert_global_centroid(session, best_g.global_id, obs.camera_id, new_centroid, batch)
        await self._repo.reactivate_if_lost(session, best_g.global_id, obs.last_seen_ts)
        # keep the GlobalID's position current for later same-batch gate checks
        await self._repo.update_global_last_position(
            session, best_g.global_id, obs.last_floor_x, obs.last_floor_y, obs.last_seen_ts
        )

    def _gate_ok(self, obs, g) -> bool:
        if g.last_floor_x is None or g.last_floor_y is None or g.last_seen_ts is None:
            return True  # no known position to contradict the match
        return cross_camera_gate(
            obs.last_floor_x, obs.last_floor_y, obs.last_seen_ts,
            g.last_floor_x, g.last_floor_y, g.last_seen_ts, self._s.max_walking_speed_mps,
        )
