"""Reconciler — owns the batch transaction and orchestrates the matcher.

Matching is spatial voting + Hungarian (primary) with an appearance fallback
for spatially-ambiguous pairs, then transitive grouping via connected
components. Pipeline per batch:

  Stage 0  camera overlap graph        (camera_zone_coverage)   [standalone read]
  ── one asyncpg transaction ──────────────────────────────────────────────────
  Stage 1  load window detections      (tracking_history)
  Stage 2  per-pair spatial voting     (spatial_voter)
  Stage 3  appearance fallback         (appearance_fallback, ambiguous only)
  Stage 4  connected components        (camera_graph)
  Stage 5  link components → GlobalIDs  (+ merge-conflict resolution)
  Stage 6  canonical position select   (PositionSelector — bucketed, unchanged)
  Stage 7  state machine               (StateManager — ACTIVE→LOST→EXITED)
  Stage 8  merge global embedding heaps (global_embeddings)
  ─────────────────────────────────────────────────────────────────────────────
  tracking_history cleanup             (separate connection, after commit)

Position selection (Stage 6) and the state machine (Stage 7) reuse the existing
PositionSelector / StateManager so the global_tracking_history output contract
(5-second bucketed positions consumed by IEP4/IEP5) is preserved.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

import numpy as np
import redis.asyncio as aioredis

from app.appearance_fallback import resolve_ambiguous
from app.camera_graph import CameraGraph, connected_components
from app.db import get_pool
from app.metrics import (
    IEP3_BATCHES,
    IEP3_CAMERAS_REPORTING,
    IEP3_ERRORS,
    IEP3_MATCHES,
    IEP3_NEW,
    IEP3_RECONCILE,
    IEP3_REID_MATCH_RATE,
    IEP3_TRANSITIONS,
)
from app.repository import Iep3Repository, merge_top_quality
from app.selection import PositionSelector
from app.settings import Iep3Settings
from app.spatial_voter import vote_camera_pair
from app.state import StateManager

logger = logging.getLogger(__name__)


class Reconciler:

    def __init__(
        self,
        store_id: str,
        repo: Iep3Repository,
        settings: Iep3Settings,
    ) -> None:
        self._store_id = store_id
        self._pool     = get_pool()   # module-level pool — created before __init__
        self._settings = settings
        self._repo     = repo

        self._batches_processed: int = 0

        # Sub-components constructed once, reused across all batches.
        self._selector = PositionSelector(repo=repo, settings=settings)
        self._state    = StateManager(repo=repo, settings=settings)

        # Lazy Redis client for the dev trace gate (VD1). Default off → no work.
        self._trace_redis: aioredis.Redis | None = None

    def _trace_client(self) -> aioredis.Redis:
        if self._trace_redis is None:
            self._trace_redis = aioredis.from_url(
                self._settings.server_redis_url, decode_responses=True
            )
        return self._trace_redis

    async def _trace_enabled(self) -> bool:
        """Redis-gated dev trace flag. Failures default to OFF (never block)."""
        try:
            return bool(await self._trace_client().get(f"iep3:debug_trace:{self._store_id}"))
        except Exception:
            return False

    async def process_batch(
        self,
        batch_number: int,
        window: tuple[int, int],
        reporting_cameras: frozenset,
    ) -> dict:
        """Run one full reconciliation cycle atomically (Stages 0–8).

        Exceptions propagate to the coordinator, which logs and skips the batch.
        Orphan sweep on the next interval cleans any partial state.
        """
        window_start_ms, window_end_ms = window
        t0 = time.monotonic()
        logger.info(
            "Reconciler starting batch=%d window=[%d, %d] cameras=%s",
            batch_number, window_start_ms, window_end_ms, sorted(reporting_cameras),
        )
        IEP3_CAMERAS_REPORTING.observe(len(reporting_cameras))

        # Dev trace (VD1): Redis-gated, default off. `trace` stays None in prod →
        # zero collection overhead; only a list when explicitly enabled.
        trace: list | None = [] if await self._trace_enabled() else None

        # ── Stage 0: camera overlap graph (read-only, outside the transaction) ──
        # Reloaded each batch so a version activation is picked up automatically.
        edges = await self._repo.get_camera_overlap_edges(self._store_id)
        graph = CameraGraph(edges)
        if trace is not None:
            trace.append({
                "event_type": "graph",
                "detail": {"pairs": [[str(a), str(b)] for a, b in graph.overlapping_pairs()]},
            })

        n_cross_links = 0
        n_new_globals = 0
        n_written = 0
        detections = []

        # Dev trace (VD1): Redis-gated, default off. `trace` stays None in prod →
        # zero collection overhead; only a list when explicitly enabled.
        trace: list | None = [] if await self._trace_enabled() else None

        # ── Stage 0: camera overlap graph (read-only, outside the transaction) ──
        # Reloaded each batch so a version activation is picked up automatically.
        edges = await self._repo.get_camera_overlap_edges(self._store_id)
        graph = CameraGraph(edges)
        if trace is not None:
            trace.append({
                "event_type": "graph",
                "detail": {"pairs": [[str(a), str(b)] for a, b in graph.overlapping_pairs()]},
            })

        n_cross_links = 0
        n_new_globals = 0
        n_written = 0
        detections = []

        async with self._pool.acquire() as conn:
            async with conn.transaction():

                # ── Stage 1: load detections ────────────────────────────────
                detections = await self._repo.read_window_detections(
                    conn, self._store_id, window_start_ms, window_end_ms
                )
                obs_by_cam, per_local = self._group(detections)

                # ── Stage 2 + 3: voting + appearance fallback → confirmed edges ─
                confirmed_edges, n_cross_links = await self._match(
                    conn, graph, obs_by_cam, per_local, trace=trace
                )

                # ── Stage 4: connected components ───────────────────────────
                nodes = [(cam, lid) for cam, locals_ in obs_by_cam.items() for lid in locals_]
                components = connected_components(nodes, confirmed_edges)

                # ── Stage 5: link components to GlobalIDs ───────────────────
                component_members, n_new_globals = await self._link_components(
                    conn, components, per_local, window_end_ms
                )

                # ── Stage 6: canonical position selection (bucketed) ────────
                n_written = await self._selector.write_canonical_positions(
                    conn=conn,
                    store_id=self._store_id,
                    batch_number=batch_number,
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                    trace=trace,
                )

                # ── Stage 7: state machine ──────────────────────────────────
                cleanup_stats = await self._state.run_cleanup(
                    conn=conn,
                    store_id=self._store_id,
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                )

                # ── Stage 8: merge global embedding heaps ───────────────────
                await self._update_global_embeddings(
                    conn, component_members, window_end_ms
                )

        # ── tracking_history cleanup (after commit, separate connection) ──────
        if reporting_cameras:
            try:
                deleted = await self._repo.delete_tracking_history_window(
                    camera_ids=list(reporting_cameras),
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                )
                logger.debug(
                    "Deleted %d tracking_history rows for batch=%d", deleted, batch_number,
                )
            except Exception:
                logger.exception(
                    "tracking_history cleanup failed for batch=%d — rows remain", batch_number,
                )

        # ── Dev trace write (VD1) — best-effort, after commit, NEVER blocks ────
        if trace:
            try:
                await self._repo.write_recon_trace(self._store_id, batch_number, trace)
            except Exception:
                logger.exception("recon_trace write failed for batch=%d (best-effort)", batch_number)

        # ── Stats + metrics ───────────────────────────────────────────────────
        reconcile_elapsed = time.monotonic() - t0
        self._batches_processed += 1
        stats = {
            "batch_number":        batch_number,
            "window_start_ms":     window_start_ms,
            "window_end_ms":       window_end_ms,
            "reporting_cameras":   sorted(reporting_cameras),
            "detections":          len(detections),
            "cross_camera_links":  n_cross_links,
            "new_globals_created": n_new_globals,
            "positions_written":   n_written,
            **cleanup_stats,
        }

        IEP3_BATCHES.inc()
        IEP3_RECONCILE.observe(reconcile_elapsed)
        IEP3_MATCHES.inc(n_cross_links)
        IEP3_NEW.inc(n_new_globals)
        IEP3_TRANSITIONS.labels(transition="lost").inc(cleanup_stats.get("newly_lost", 0))
        IEP3_TRANSITIONS.labels(transition="exited").inc(cleanup_stats.get("newly_exited", 0))
        IEP3_CAMERAS_REPORTING.observe(len(reporting_cameras))
        # ReID match rate = identities matched to an existing global / total
        # resolved identities this batch. component_members is keyed by global_id,
        # so its size is the total; n_new_globals of those were freshly created.
        n_known = len(component_members) - n_new_globals
        total_locals = len(component_members)
        if total_locals > 0:
            IEP3_REID_MATCH_RATE.set(n_known / total_locals)

        logger.info("Batch %d reconciled: %s", batch_number, stats)

        # Periodic orphan sweep (skip if reconciliation ran long).
        if self._batches_processed % self._settings.orphan_sweep_interval_batches == 0:
            if reconcile_elapsed < self._settings.window_seconds * 0.8:
                try:
                    await self._repo.orphan_sweep(self._store_id)
                except Exception:
                    IEP3_ERRORS.labels(error_type="orphan_sweep").inc()
                    logger.exception(
                        "Periodic orphan sweep failed at batch=%d — skipping",
                        batch_number,
                    )
            else:
                logger.info(
                    "Skipping orphan sweep — reconciliation took %.1fs (>80%% of %.0fs window)",
                    reconcile_elapsed, self._settings.window_seconds,
                )

        return stats

    # ── helpers ───────────────────────────────────────────────────────────────

    def _group(self, detections):
        """Group detections into per-camera observations and per-local summaries.

        Returns:
          obs_by_cam: {camera_id: {local_id: [(ts, x, y), ...]}}
          per_local:  {local_id: {"camera", "first_ts", "last_ts", "fx", "fy"}}
        Detections are ordered by timestamp ASC, so the last write wins for
        last_ts/floor and the first sets first_ts.
        """
        obs_by_cam: dict = defaultdict(lambda: defaultdict(list))
        per_local: dict = {}
        for d in detections:
            obs_by_cam[d.camera_id][d.local_id].append((d.timestamp_ms, d.floor_x, d.floor_y))
            pl = per_local.get(d.local_id)
            if pl is None:
                per_local[d.local_id] = {
                    "camera": d.camera_id, "first_ts": d.timestamp_ms,
                    "last_ts": d.timestamp_ms, "fx": d.floor_x, "fy": d.floor_y,
                }
            else:
                pl["last_ts"] = d.timestamp_ms
                pl["fx"], pl["fy"] = d.floor_x, d.floor_y
        return obs_by_cam, per_local

    async def _match(self, conn, graph, obs_by_cam, per_local, trace=None):
        """Stages 2 + 3 — return (confirmed_edges, n_cross_links).

        confirmed_edges: list of ((cam_a, local_a), (cam_b, local_b)).
        When `trace` is set (dev VD1), spatial_vote + reid_fallback events are
        appended from values the voter/fallback already computed.
        """
        s = self._settings
        confirmed_edges: list = []
        ambiguous_all: list = []   # (cam_a, local_a, cam_b, local_b, vote_rate)

        for cam_a, cam_b in graph.overlapping_pairs():
            if cam_a not in obs_by_cam or cam_b not in obs_by_cam:
                continue
            vote_details = [] if trace is not None else None
            confirmed, ambiguous = vote_camera_pair(
                obs_by_cam[cam_a], obs_by_cam[cam_b],
                vote_distance_threshold_m=s.vote_distance_threshold_m,
                min_vote_rate=s.min_vote_rate,
                min_votes=s.min_votes,
                temporal_tolerance_ms=s.temporal_tolerance_ms,
                ambiguity_margin=s.ambiguity_margin,
                details=vote_details,
            )
            for la, lb, _vr in confirmed:
                confirmed_edges.append(((cam_a, la), (cam_b, lb)))
            for la, lb, vr in ambiguous:
                ambiguous_all.append((cam_a, la, cam_b, lb, vr))

            if trace is not None and vote_details:
                for d in vote_details:
                    trace.append({"event_type": "spatial_vote", "detail": {
                        "cam_a": str(cam_a), "local_a": str(d["local_a"]),
                        "cam_b": str(cam_b), "local_b": str(d["local_b"]),
                        "vote_rate": d["vote_rate"], "votes": d["votes"],
                        "co_visible": d["co_visible"], "class": d["class"],
                    }})

        # Stage 3 — appearance fallback for ambiguous pairs only.
        if ambiguous_all:
            cand_locals = {la for _, la, _, _, _ in ambiguous_all} | {
                lb for _, _, _, lb, _ in ambiguous_all
            }
            heaps = await self._repo.get_local_heaps_bulk(conn, list(cand_locals))
            embeddings = {
                lid: np.array([e for _, e in heap], dtype=np.float32)
                for lid, heap in heaps.items()
            }
            amb_pairs = [(la, lb, vr) for _, la, _, lb, vr in ambiguous_all]
            reid_details = [] if trace is not None else None
            for la, lb, _vr in resolve_ambiguous(
                amb_pairs, embeddings,
                reid_fallback_threshold=s.reid_fallback_threshold,
                details=reid_details,
            ):
                cam_a = per_local[la]["camera"]
                cam_b = per_local[lb]["camera"]
                confirmed_edges.append(((cam_a, la), (cam_b, lb)))

            if trace is not None and reid_details:
                for d in reid_details:
                    ca = per_local.get(d["local_a"], {}).get("camera")
                    cb = per_local.get(d["local_b"], {}).get("camera")
                    trace.append({"event_type": "reid_fallback", "detail": {
                        "cam_a": str(ca), "local_a": str(d["local_a"]),
                        "cam_b": str(cb), "local_b": str(d["local_b"]),
                        "cosine": d["cosine"], "threshold": d["threshold"],
                        "matched": d["matched"], "final_score": d["final_score"],
                    }})

        return confirmed_edges, len(confirmed_edges)

    async def _link_components(self, conn, components, per_local, window_end_ms):
        """Stage 5 — attach each component to a GlobalID. Returns (members, n_new)."""
        component_members: dict = {}   # global_id -> list[(camera, local)]
        n_new = 0

        for comp in components:
            comp_locals = [lid for _cam, lid in comp]
            existing = await self._repo.find_global_ids_for_locals(conn, comp_locals)

            if not existing:
                # New identity — anchor on the earliest-seen member's position.
                earliest = min(comp, key=lambda n: per_local[n[1]]["first_ts"])
                pl = per_local[earliest[1]]
                global_id = await self._repo.create_global_identity(
                    conn=conn, store_id=self._store_id,
                    first_seen_ts=pl["first_ts"], last_floor_x=pl["fx"], last_floor_y=pl["fy"],
                )
                n_new += 1
            else:
                # Reuse the oldest global; merge-conflict the rest.
                existing.sort(key=lambda t: t[1])  # by first_seen_ts ASC
                global_id = existing[0][0]
                discard = [g for g, _ in existing[1:] if g != global_id]
                if discard:
                    await self._repo.merge_globals(conn, global_id, discard, window_end_ms)
                    logger.warning(
                        "Merge conflict: component spanned %d globals — kept %s, exited %s",
                        len(existing), global_id, discard,
                    )

            for cam, lid in comp:
                pl = per_local[lid]
                await self._repo.link_member(
                    conn=conn, global_id=global_id, camera_id=cam, local_id=lid,
                    linked_at_ts=pl["first_ts"], last_seen_ts=pl["last_ts"],
                )
            component_members[global_id] = list(comp)

        return component_members, n_new

    async def _update_global_embeddings(self, conn, component_members, window_end_ms):
        """Stage 8 — fold each member's local heap into its global embedding store."""
        all_locals = [lid for members in component_members.values() for _cam, lid in members]
        if not all_locals:
            return
        local_heaps = await self._repo.get_local_heaps_bulk(conn, all_locals)

        for global_id, members in component_members.items():
            for cam, lid in members:
                incoming = local_heaps.get(lid)
                if not incoming:
                    continue
                existing = await self._repo.get_global_embeddings_packed(conn, global_id, cam)
                merged = merge_top_quality(existing, incoming, self._settings.max_embeddings)
                await self._repo.upsert_global_embedding_packed(
                    conn=conn, global_id=global_id, camera_id=cam,
                    heap=merged, updated_at_ts=window_end_ms,
                )
