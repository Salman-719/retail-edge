"""ReidMatcher — Process 1: links new LocalIDs to existing or new GlobalIDs.
Operates inside the Reconciler's single transaction (conn passed by caller).
"""
from __future__ import annotations

import logging
import uuid

import asyncpg
import numpy as np

from app.repository import Iep3Repository, LocalObservation, GlobalCandidate
from app.reid.gates import cross_camera_gate

logger = logging.getLogger(__name__)


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm < 1e-8:
        return v   # zero vector — cosine similarity will be ~0, below threshold
    return v / norm


def _representative_centroid(
    camera_centroids: list[tuple[str, np.ndarray]],
) -> np.ndarray:
    """L2-normalize the mean of all per-camera centroids."""
    vecs = [c for _, c in camera_centroids]
    return _l2_normalize(np.mean(vecs, axis=0))


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Dot product of two L2-normalized vectors."""
    return float(np.dot(_l2_normalize(a), b))


class ReidMatcher:

    def __init__(
        self,
        repo: Iep3Repository,
        reid_threshold: float,
        max_speed_mps: float,
        embedding_dim: int,
    ) -> None:
        self._repo = repo
        self._threshold = reid_threshold
        self._max_speed = max_speed_mps
        self._embedding_dim = embedding_dim

    async def link_new_locals(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        new_observations: list[LocalObservation],
        batch_number: int,
        window_end_ms: int,
    ) -> int:
        """Link all new LocalIDs to GlobalIDs.

        Returns count of new GlobalIDs created.
        new_observations must be sorted by first_seen_ts ASC (guaranteed by C4).
        Candidate globals and embeddings loaded once before the loop — never
        re-queried inside it.
        """
        if not new_observations:
            return 0

        # Load candidate globals (ACTIVE + LOST) once before the loop
        candidates: list[GlobalCandidate] = await self._repo.get_candidate_globals(
            conn, store_id
        )

        # Load all per-camera embeddings for all candidates in one query
        candidate_ids = [c.global_id for c in candidates]
        embedding_map: dict[uuid.UUID, list[tuple[str, np.ndarray]]] = (
            await self._repo.get_embeddings_bulk(conn, candidate_ids)
        )

        new_global_count = 0

        for obs in new_observations:
            created = await self._process_one(
                conn=conn,
                store_id=store_id,
                obs=obs,
                candidates=candidates,        # mutated in-place as globals created
                embedding_map=embedding_map,  # mutated in-place as globals created
                batch_number=batch_number,
                window_end_ms=window_end_ms,
            )
            if created:
                new_global_count += 1

        logger.info(
            "ReidMatcher: processed %d new locals — %d new GlobalIDs created",
            len(new_observations), new_global_count,
        )
        return new_global_count

    async def _process_one(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        obs: LocalObservation,
        candidates: list[GlobalCandidate],
        embedding_map: dict[uuid.UUID, list[tuple[str, np.ndarray]]],
        batch_number: int,
        window_end_ms: int,
    ) -> bool:
        """Process one new LocalID. Returns True if a new GlobalID was created.

        Mutates candidates and embedding_map to include newly created GlobalIDs
        so subsequent iterations can match against them.
        """
        # Load appearance centroid for this LocalID
        centroid = await self._repo.load_local_centroid(conn, obs.local_id)
        if centroid is None:
            logger.warning(
                "No centroid for local_id=%s camera=%s — "
                "creating new GlobalID without ReID matching",
                obs.local_id, obs.camera_id,
            )
            await self._create_new_global(
                conn, store_id, obs, centroid=None,
                candidates=candidates, embedding_map=embedding_map,
                batch_number=batch_number,
            )
            return True

        # Step 1: cross-camera filter — exclude candidates with an active link
        # on obs.camera_id (within-camera continuity is IEP2's responsibility)
        eligible = [
            c for c in candidates
            if obs.camera_id not in c.active_camera_ids
        ]

        # Step 2: spatial-temporal gate — exclude physically impossible movements.
        # NULL coordinates (uncalibrated camera) are handled inside the gate
        # (R5): gate passes and relies on appearance similarity only.
        survivors = []
        for candidate in eligible:
            if cross_camera_gate(
                new_x=obs.last_floor_x,
                new_y=obs.last_floor_y,
                new_ts=obs.last_seen_ts,
                last_x=candidate.last_floor_x,
                last_y=candidate.last_floor_y,
                last_ts=candidate.last_seen_ts,
                max_speed_mps=self._max_speed,
            ):
                survivors.append(candidate)

        if not survivors:
            await self._create_new_global(
                conn, store_id, obs, centroid=centroid,
                candidates=candidates, embedding_map=embedding_map,
                batch_number=batch_number,
            )
            return True

        # Step 3: cosine similarity against representative centroids
        best_global_id: uuid.UUID | None = None
        best_score: float = -1.0

        for candidate in survivors:
            cam_centroids = embedding_map.get(candidate.global_id, [])
            if not cam_centroids:
                # GlobalID just created this batch without a centroid — skip
                continue
            rep = _representative_centroid(cam_centroids)
            score = _cosine_similarity(centroid, rep)
            if score > best_score:
                best_score = score
                best_global_id = candidate.global_id

        if best_global_id is None or best_score < self._threshold:
            await self._create_new_global(
                conn, store_id, obs, centroid=centroid,
                candidates=candidates, embedding_map=embedding_map,
                batch_number=batch_number,
            )
            return True

        # Step 4: link or reactivate
        best_candidate = next(
            c for c in survivors if c.global_id == best_global_id
        )

        if best_candidate.state == "lost":
            await self._repo.reactivate_global(
                conn=conn,
                global_id=best_global_id,
                local_id=obs.local_id,
                camera_id=obs.camera_id,
                linked_at_ts=obs.first_seen_ts,
                last_seen_ts=obs.last_seen_ts,
                last_floor_x=obs.last_floor_x,
                last_floor_y=obs.last_floor_y,
            )
            best_candidate.state = "active"
            logger.info(
                "Reactivated LOST GlobalID=%s via camera=%s score=%.3f",
                best_global_id, obs.camera_id, best_score,
            )
        else:
            await self._repo.link_local(
                conn=conn,
                global_id=best_global_id,
                camera_id=obs.camera_id,
                local_id=obs.local_id,
                linked_at_ts=obs.first_seen_ts,
            )
            logger.debug(
                "Linked local_id=%s → GlobalID=%s camera=%s score=%.3f",
                obs.local_id, best_global_id, obs.camera_id, best_score,
            )

        # Update in-memory candidate state — must happen before next iteration
        best_candidate.active_camera_ids.add(obs.camera_id)
        best_candidate.last_floor_x = obs.last_floor_x
        best_candidate.last_floor_y = obs.last_floor_y
        best_candidate.last_seen_ts = obs.last_seen_ts

        # UPSERT embedding for this camera
        centroid_bytes = centroid.astype(np.float32).tobytes()
        await self._repo.upsert_embedding(
            conn=conn,
            global_id=best_global_id,
            camera_id=obs.camera_id,
            centroid_bytes=centroid_bytes,
            updated_at_ts=obs.last_seen_ts,
        )
        # Update in-memory embedding map — replace existing entry or append
        cam_list = embedding_map.setdefault(best_global_id, [])
        for i, (cid, _) in enumerate(cam_list):
            if cid == obs.camera_id:
                cam_list[i] = (obs.camera_id, centroid)
                break
        else:
            cam_list.append((obs.camera_id, centroid))

        return False  # no new GlobalID created

    async def _create_new_global(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        obs: LocalObservation,
        centroid: np.ndarray | None,
        candidates: list[GlobalCandidate],
        embedding_map: dict[uuid.UUID, list[tuple[str, np.ndarray]]],
        batch_number: int,
    ) -> uuid.UUID:
        """Create a new GlobalID, link obs.local_id, store embedding.

        Appends the new GlobalID to candidates and embedding_map immediately
        so subsequent LocalIDs in the same batch can match against it.
        """
        global_id = await self._repo.create_global_identity(
            conn=conn,
            store_id=store_id,
            first_seen_ts=obs.first_seen_ts,
            last_floor_x=obs.last_floor_x,
            last_floor_y=obs.last_floor_y,
        )
        await self._repo.link_local(
            conn=conn,
            global_id=global_id,
            camera_id=obs.camera_id,
            local_id=obs.local_id,
            linked_at_ts=obs.first_seen_ts,
        )
        if centroid is not None:
            await self._repo.upsert_embedding(
                conn=conn,
                global_id=global_id,
                camera_id=obs.camera_id,
                centroid_bytes=centroid.astype(np.float32).tobytes(),
                updated_at_ts=obs.last_seen_ts,
            )
            embedding_map[global_id] = [(obs.camera_id, centroid)]
        else:
            embedding_map[global_id] = []

        # Add to in-memory candidate pool — available to subsequent iterations
        candidates.append(GlobalCandidate(
            global_id=global_id,
            state="active",
            last_floor_x=obs.last_floor_x,
            last_floor_y=obs.last_floor_y,
            last_seen_ts=obs.last_seen_ts,
            active_camera_ids={obs.camera_id},
        ))

        logger.info(
            "New GlobalID=%s created for local_id=%s camera=%s",
            global_id, obs.local_id, obs.camera_id,
        )
        return global_id
