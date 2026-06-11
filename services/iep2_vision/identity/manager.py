"""LocalIdentityManager — stable Local ID assignment with occlusion recovery.

Lifecycle:
  new track (lost pool empty)  → fast path → ActiveTrack immediately
  new track (lost pool non-empty) → PendingTrack → collect init embeddings
                                    → ReID against lost pool → recover or mint
  disappeared active track     → LostEntry (with gallery, TTL)
  disappeared pending track    → dropped silently (no local_id ever minted)
"""
import asyncio
import logging
import os

import numpy as np

log = logging.getLogger("iep2.identity")

try:
    from .pools import ActiveTrack, PendingTrack, LostEntry
    from .gallery import EmbeddingGallery
except ImportError:
    import sys as _sys, os as _os
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path.insert(0, _here)
    from pools import ActiveTrack, PendingTrack, LostEntry
    from gallery import EmbeddingGallery

# ── Constants (single source of truth) ────────────────────────────────────────
TTL_FRAMES                 = 150   # 30 s at 5 fps
# ReID scheduling knobs — env-tunable so the crop volume can be dialled down as
# camera count grows (each extraction is GPU + per-crop CPU overhead). Defaults
# preserve prior behaviour; raise REID_SAMPLE_EVERY_N at scale to sample less often.
INIT_EMBEDDINGS_COUNT      = int(os.environ.get("REID_INIT_COUNT", "5"))       # embeddings collected before ReID attempt
SAMPLE_INTERVAL            = int(os.environ.get("REID_SAMPLE_EVERY_N", "15"))  # frames between samples in sampled phase
MIN_BBOX_HEIGHT_PX         = 64    # quality gate: min bbox pixel height for a sampled crop
MIN_BBOX_CONFIDENCE        = 0.5   # quality gate: min YOLO confidence for a sampled crop
# Cosine threshold for lost-pool occlusion recovery (resnet50_msmt17). Tunable
# via the REID_MATCH_THRESHOLD env var without a code change (default 0.75).
REID_MATCH_THRESHOLD = float(os.environ.get("REID_MATCH_THRESHOLD", "0.75"))


def _quality_score(confidence: float, bbox, frame_height: int) -> float:
    """Per-embedding quality = confidence * (bbox_height_px / frame_height_px).

    Normalises bbox height by frame height so crops from cameras of different
    resolutions are comparable. Result is clamped to [0, 1]. Drives which
    embeddings survive in the gallery heap and feed IEP3 matching.
    """
    if frame_height <= 0:
        return 0.0
    bbox_h = max(0.0, float(bbox[3] - bbox[1]))
    return float(np.clip(float(confidence) * (bbox_h / frame_height), 0.0, 1.0))


class LocalIdentityManager:
    def __init__(
        self,
        reid_client,
        camera_id: str = "",
        redis_local=None,
        embedding_loader=None,
    ):
        """reid_client: ReidClient; camera_id + redis_local enable Redis counter persistence (R5).

        embedding_loader: optional ``async (local_id_int) -> (embeddings_bytes,
        count, quality_bytes) | None`` used to restore a gallery heap from
        local_centroids when a persisted local_id reappears (restart / post-TTL
        BoTSORT reuse). None disables recovery (dev/video paths).
        """
        self._reid_client = reid_client
        self._camera_id = camera_id
        self._redis = redis_local
        self._embedding_loader = embedding_loader
        self._active:  dict[int, ActiveTrack]  = {}
        self._pending: dict[int, PendingTrack] = {}
        self._lost:    dict[int, LostEntry]    = {}
        # Sticky mapping: once a track_id is assigned a local_id, the binding is permanent.
        self._track_to_local: dict[int, int] = {}
        self._next_id: int = self._load_counter()
        self._frame_index: int = 0
        # Debug only: best lost-pool cosine similarity recorded when each local_id
        # was resolved {local_id: {"sim": float|None, "matched": bool}}. Surfaced
        # to the dev screen via the live stream so ReID decisions are inspectable.
        self._reid_debug: dict[int, dict] = {}

    def _load_counter(self) -> int:
        if self._redis is None or not self._camera_id:
            return 1
        try:
            val = self._redis.get(f"iep2:id_counter:{self._camera_id}")
            return int(val) + 1 if val else 1
        except Exception:
            return 1

    def _persist_counter(self) -> None:
        if self._redis is None or not self._camera_id:
            return
        try:
            self._redis.set(f"iep2:id_counter:{self._camera_id}", self._next_id - 1)
        except Exception:
            pass  # counter is best-effort; collision risk is low

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process_frame(
        self,
        frame: np.ndarray,
        tracks: list[dict],
        timestamp_ms: int = 0,
    ) -> tuple[list[dict], int, int]:
        """Run the full identity lifecycle for one frame.

        Returns (enriched, reid_crops, reid_batches) where:
          reid_crops   — total number of crops sent to ReID this frame
          reid_batches — number of asyncio.gather calls made (batch invocations)
        Active tracks carry an int local_id; pending tracks carry None.
        Input list is never mutated.
        """
        # Stage 0 — advance frame counter
        self._frame_index += 1
        _reid_crops   = 0
        _reid_batches = 0

        # Stage 1 — prune expired lost entries
        expired = [
            lid for lid, entry in self._lost.items()
            if self._frame_index - entry.lost_at_frame > TTL_FRAMES
        ]
        for lid in expired:
            del self._lost[lid]
            log.info("F%04d  TTL expired  local_id=%d  pruned from lost pool", self._frame_index, lid)

        # Stage 2 — handle disappeared tracks
        current_ids = {t["track_id"] for t in tracks}
        disappeared_active  = [tid for tid in self._active  if tid not in current_ids]
        disappeared_pending = [tid for tid in self._pending if tid not in current_ids]

        for tid in disappeared_active:
            entry = self._active.pop(tid)
            self._lost[entry.local_id] = LostEntry(
                local_id=entry.local_id,
                lost_at_frame=self._frame_index,
                gallery=entry.gallery,
                last_floor_pos=entry.last_floor_pos,
            )
            log.info(
                "F%04d  track disappeared  track_id=%d  local_id=%d  → lost pool (TTL=%d frames)",
                self._frame_index, tid, entry.local_id, TTL_FRAMES,
            )

        for tid in disappeared_pending:
            del self._pending[tid]  # dropped silently — no local_id ever minted
            log.info("F%04d  pending track dropped  track_id=%d  (never resolved)", self._frame_index, tid)

        # Stage 3 — process each current track
        # Tracks that qualify for a global sample-tick ReID call this frame:
        # list of (active_track, track_dict) — populated below, fired after the loop.
        sample_candidates: list[tuple] = []

        enriched: list[dict] = []
        for track in tracks:
            tid = track["track_id"]

            # ── Branch A: already active ───────────────────────────────────────
            if tid in self._active:
                active = self._active[tid]

                floor_x = track.get("floor_x")
                floor_y = track.get("floor_y")
                if floor_x is not None and floor_y is not None:
                    active.last_floor_pos = (floor_x, floor_y)

                if active.gallery.is_init_phase:
                    # Buffer the raw crop (+ its confidence); send to ReID only
                    # when we have a full batch. Init crops are not quality-gated
                    # — birth embeddings are needed for occlusion recovery — but
                    # each carries a quality score so it competes in the heap.
                    active.init_crops.append(
                        (frame, track["bbox"], track.get("confidence", 0.0), timestamp_ms)
                    )

                    if len(active.init_crops) >= INIT_EMBEDDINGS_COUNT:
                        # Batch-extract all buffered init crops in parallel.
                        results = await asyncio.gather(*[
                            self._reid_client.extract(
                                f, bbox, track_id=tid, timestamp_ms=ts
                            )
                            for f, bbox, conf, ts in active.init_crops
                        ])
                        _reid_crops   += len(active.init_crops)
                        _reid_batches += 1
                        for (f, bbox, conf, ts), emb in zip(active.init_crops, results):
                            if emb is not None:
                                q = _quality_score(conf, bbox, f.shape[0])
                                active.gallery.add(emb, q, is_init=True)
                        active.init_crops.clear()
                        log.debug(
                            "F%04d  init batch flushed  track_id=%d  local_id=%d",
                            self._frame_index, tid, active.local_id,
                        )
                    else:
                        log.debug(
                            "F%04d  init buffering  track_id=%d  crops=%d/%d",
                            self._frame_index, tid,
                            len(active.init_crops), INIT_EMBEDDINGS_COUNT,
                        )
                else:
                    # Sampled phase: collect on global tick (fired after the loop).
                    # Quality gate (min height + min confidence) skips weak crops
                    # before spending ReID inference on them.
                    if self._frame_index % SAMPLE_INTERVAL == 0:
                        conf = track.get("confidence", 0.0)
                        x1, y1, x2, y2 = track["bbox"]
                        bbox_height = y2 - y1
                        if (conf >= MIN_BBOX_CONFIDENCE
                                and bbox_height >= MIN_BBOX_HEIGHT_PX):
                            sample_candidates.append((active, track))

                enriched.append({**track, "local_id": active.local_id})

            # ── Branch B: pending, buffering crops until we have a full init batch ──
            elif tid in self._pending:
                pending = self._pending[tid]
                pending.init_crops.append(
                    (frame, track["bbox"], track.get("confidence", 0.0), timestamp_ms)
                )

                if len(pending.init_crops) >= INIT_EMBEDDINGS_COUNT:
                    results = await asyncio.gather(*[
                        self._reid_client.extract(
                            f, bbox, track_id=tid, timestamp_ms=ts
                        )
                        for f, bbox, conf, ts in pending.init_crops
                    ])
                    _reid_crops   += len(pending.init_crops)
                    _reid_batches += 1
                    for (f, bbox, conf, ts), emb in zip(pending.init_crops, results):
                        if emb is not None:
                            q = _quality_score(conf, bbox, f.shape[0])
                            pending.init_embeddings.append((emb, q))
                    pending.init_crops.clear()

                if len(pending.init_embeddings) >= INIT_EMBEDDINGS_COUNT:
                    local_id, gallery = self._resolve_pending(pending)
                    self._active[tid] = ActiveTrack(
                        local_id=local_id, track_id=tid, gallery=gallery
                    )
                    del self._pending[tid]
                    enriched.append({**track, "local_id": local_id})
                else:
                    log.debug(
                        "F%04d  collecting  track_id=%d  crops=%d/%d",
                        self._frame_index, tid,
                        len(pending.init_crops) + len(pending.init_embeddings),
                        INIT_EMBEDDINGS_COUNT,
                    )
                    enriched.append({**track, "local_id": None})

            # ── Branch C: first appearance ─────────────────────────────────────
            else:
                if tid in self._track_to_local:
                    # BoTSORT re-surfaced a known track_id — restore prior local_id immediately.
                    local_id = self._track_to_local[tid]
                    if local_id in self._lost:
                        lost_entry = self._lost.pop(local_id)
                        gallery = lost_entry.gallery
                        log.info(
                            "F%04d  BoTSORT reuse  track_id=%d  → local_id=%d  (restored from lost pool)",
                            self._frame_index, tid, local_id,
                        )
                    else:
                        # Past TTL — the in-memory gallery is gone. Try to restore
                        # the persisted heap from local_centroids (restart recovery).
                        gallery = await self._restore_gallery(local_id)
                        log.info(
                            "F%04d  BoTSORT reuse (post-TTL)  track_id=%d  → local_id=%d  (gallery restored=%s)",
                            self._frame_index, tid, local_id, len(gallery) > 0,
                        )
                    self._active[tid] = ActiveTrack(local_id=local_id, track_id=tid, gallery=gallery)
                    enriched.append({**track, "local_id": local_id})

                elif not self._lost:
                    # Fast path — no occlusion candidates, assign immediately
                    local_id = self._next_id
                    self._next_id += 1
                    self._persist_counter()
                    gallery = EmbeddingGallery()
                    self._active[tid] = ActiveTrack(
                        local_id=local_id, track_id=tid, gallery=gallery
                    )
                    self._track_to_local[tid] = local_id
                    log.info(
                        "F%04d  new track (fast path)  track_id=%d  → local_id=%d",
                        self._frame_index, tid, local_id,
                    )
                    enriched.append({**track, "local_id": local_id})
                else:
                    # Normal path — may be a re-entry; hold in pending
                    self._pending[tid] = PendingTrack(track_id=tid)
                    log.info(
                        "F%04d  new track (pending)  track_id=%d  lost_pool_size=%d",
                        self._frame_index, tid, len(self._lost),
                    )
                    enriched.append({**track, "local_id": None})

        # Stage 4 — global sample tick: batch-extract for all sampled-phase candidates.
        if sample_candidates:
            results = await asyncio.gather(*[
                self._reid_client.extract(
                    frame, t_dict["bbox"],
                    track_id=t_dict["track_id"], timestamp_ms=timestamp_ms,
                )
                for _, t_dict in sample_candidates
            ])
            _reid_crops   += len(sample_candidates)
            _reid_batches += 1
            for (active, t_dict), emb in zip(sample_candidates, results):
                if emb is not None:
                    q = _quality_score(
                        t_dict.get("confidence", 0.0), t_dict["bbox"], frame.shape[0]
                    )
                    active.gallery.add(emb, q, is_init=False)
            log.debug(
                "F%04d  sample tick  candidates=%d",
                self._frame_index, len(sample_candidates),
            )

        # Debug: annotate each track with the lost-pool similarity recorded when
        # its local_id was resolved (None for fast-path / BoTSORT-reuse, which do
        # no appearance comparison). Lets the dev screen show ReID confidence.
        for t in enriched:
            dbg = self._reid_debug.get(t.get("local_id"))
            if dbg is not None:
                t["reid_sim"] = dbg["sim"]
                t["reid_matched"] = dbg["matched"]

        return enriched, _reid_crops, _reid_batches

    def get_active_embeddings_packed(self) -> dict[int, tuple[bytes, int, bytes]]:
        """Return {local_id_int: (embeddings_bytes, embedding_count, quality_scores_bytes)}.

        One entry per currently-active track whose gallery is non-empty. This is
        the batch-end snapshot written to local_centroids (replaces the old
        single-centroid get_active_centroids).
        """
        result: dict[int, tuple[bytes, int, bytes]] = {}
        for active_track in self._active.values():
            packed = active_track.gallery.export_packed()
            if packed is not None:
                result[active_track.local_id] = packed
        return result

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _restore_gallery(self, local_id: int) -> EmbeddingGallery:
        """Build a gallery for an existing local_id, restoring its persisted heap.

        Uses the optional embedding_loader to read local_centroids. Returns an
        empty gallery if no loader is configured, no row exists, or loading fails.
        """
        gallery = EmbeddingGallery()
        if self._embedding_loader is None:
            return gallery
        try:
            packed = await self._embedding_loader(local_id)
            if packed is not None:
                gallery.load_packed(*packed)
        except Exception as exc:
            log.warning("Gallery restore failed for local_id=%d: %s", local_id, exc)
        return gallery

    def _resolve_pending(self, pending: PendingTrack):
        """Match pending init embeddings against the lost pool (appearance only).

        pending.init_embeddings holds (embedding, quality_score) tuples; the
        mean used for lost-pool matching ignores the scores.
        """
        init_embs = [e for e, _ in pending.init_embeddings]
        mean_emb = np.mean(init_embs, axis=0).astype(np.float32)
        norm = np.linalg.norm(mean_emb)
        if norm > 0:
            mean_emb = mean_emb / norm

        best_sim = -1.0
        best_lid = None

        # Pure appearance matching against the lost pool — no spatial/temporal
        # gate. Every lost candidate is eligible; the best cosine match above
        # REID_MATCH_THRESHOLD wins.
        for lid, lost_entry in self._lost.items():
            centroid = lost_entry.gallery.snapshot_centroid()
            if centroid is None:
                continue
            sim = float(np.dot(mean_emb, centroid))
            if sim > best_sim:
                best_sim = sim
                best_lid = lid

        if best_lid is not None and best_sim >= REID_MATCH_THRESHOLD:
            lost_entry = self._lost.pop(best_lid)
            local_id = lost_entry.local_id
            gallery = lost_entry.gallery
            self._track_to_local[pending.track_id] = local_id
            log.info(
                "F%04d  ReID MATCH  track_id=%d  → local_id=%d  sim=%.3f  (threshold=%.2f)",
                self._frame_index, pending.track_id, local_id, best_sim, REID_MATCH_THRESHOLD,
            )
        else:
            local_id = self._next_id
            self._next_id += 1
            self._persist_counter()
            gallery = EmbeddingGallery()
            self._track_to_local[pending.track_id] = local_id
            log.info(
                "F%04d  ReID NO MATCH  track_id=%d  → new local_id=%d  best_sim=%.3f  (threshold=%.2f)",
                self._frame_index, pending.track_id, local_id,
                best_sim if best_lid is not None else 0.0, REID_MATCH_THRESHOLD,
            )

        # Record the best lost-pool similarity for this resolution so the dev
        # screen can show why a candidate matched (or was minted new). sim is None
        # when there was no comparable lost candidate (empty pool / no centroid).
        self._reid_debug[local_id] = {
            "sim": float(best_sim) if best_lid is not None else None,
            "matched": bool(best_lid is not None and best_sim >= REID_MATCH_THRESHOLD),
        }

        for emb, q in pending.init_embeddings:
            gallery.add(emb, q, is_init=True)

        return local_id, gallery


# ---------------------------------------------------------------------------
# Standalone smoke test: python identity/manager.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    class _MockReidClient:
        """Injects a controlled embedding regardless of crop content."""
        def __init__(self):
            self.emb = np.zeros(2048, dtype=np.float32)

        async def start(self): pass
        async def close(self): pass

        async def extract(self, frame, bbox, track_id, timestamp_ms):
            return self.emb.copy()

    async def _run_tests():
        mock = _MockReidClient()
        mgr  = LocalIdentityManager(mock)

        emb_a = np.zeros(2048, dtype=np.float32); emb_a[0] = 1.0
        emb_b = np.zeros(2048, dtype=np.float32); emb_b[1] = 1.0

        frame = np.zeros((200, 300, 3), dtype=np.uint8)
        bbox  = [10, 10, 110, 160]

        def _track(tid):
            return {"track_id": tid, "label": "person", "confidence": 0.9, "bbox": bbox}

        # ── Test 1: fast path ─────────────────────────────────────────────────
        mock.emb = emb_a
        r, _, _ = await mgr.process_frame(frame, [_track(1)])
        local_id_a = r[0]["local_id"]
        assert local_id_a == 1, f"fast path: expected 1, got {local_id_a}"

        # Send enough frames to flush the init batch (INIT_EMBEDDINGS_COUNT) so
        # the gallery is populated before the track disappears — otherwise the
        # lost entry has an empty gallery and cannot be recovered in Test 3.
        for _ in range(INIT_EMBEDDINGS_COUNT):
            await mgr.process_frame(frame, [_track(1)])

        await mgr.process_frame(frame, [])
        assert 1 in mgr._lost, "local_id 1 should be in lost pool"
        print(f"[1] fast path + disappear → lost pool ✓  (local_id={local_id_a})")

        # ── Test 2: orthogonal person ─────────────────────────────────────────
        mock.emb = emb_b
        r, _, _ = await mgr.process_frame(frame, [_track(2)])
        assert r[0]["local_id"] is None

        for _ in range(INIT_EMBEDDINGS_COUNT - 1):
            r, _, _ = await mgr.process_frame(frame, [_track(2)])
            assert r[0]["local_id"] is None

        r, _, _ = await mgr.process_frame(frame, [_track(2)])
        local_id_b = r[0]["local_id"]
        assert local_id_b is not None
        assert local_id_b != local_id_a
        print(f"[2] orthogonal person → new local_id={local_id_b} ✓")

        await mgr.process_frame(frame, [])

        # ── Test 3: same person recovers local_id ─────────────────────────────
        mock.emb = emb_a
        r, _, _ = await mgr.process_frame(frame, [_track(3)])
        assert r[0]["local_id"] is None

        for _ in range(INIT_EMBEDDINGS_COUNT - 1):
            r, _, _ = await mgr.process_frame(frame, [_track(3)])

        r, _, _ = await mgr.process_frame(frame, [_track(3)])
        recovered_id = r[0]["local_id"]
        assert recovered_id == local_id_a
        print(f"[3] ReID recovery → local_id={recovered_id} == original {local_id_a} ✓")

        # ── Test 4: pending dropped ───────────────────────────────────────────
        mgr2 = LocalIdentityManager(_MockReidClient())
        mock2 = mgr2._reid_client
        mock2.emb = emb_a
        await mgr2.process_frame(frame, [_track(1)])
        await mgr2.process_frame(frame, [])
        await mgr2.process_frame(frame, [_track(99)])
        assert 99 in mgr2._pending
        await mgr2.process_frame(frame, [])
        assert 99 not in mgr2._pending
        print("[4] pending disappear → silently dropped ✓")

        # ── Test 5: TTL + sticky mapping ─────────────────────────────────────
        mgr3 = LocalIdentityManager(_MockReidClient())
        mgr3._reid_client.emb = emb_a
        await mgr3.process_frame(frame, [_track(1)])
        await mgr3.process_frame(frame, [])
        for _ in range(TTL_FRAMES + 1):
            await mgr3.process_frame(frame, [])
        assert len(mgr3._lost) == 0
        r, _, _ = await mgr3.process_frame(frame, [_track(1)])
        assert r[0]["local_id"] == 1
        print(f"[5] TTL + sticky → local_id={r[0]['local_id']} ✓")

        # ── Test 6: BoTSORT reuse ─────────────────────────────────────────────
        mgr4 = LocalIdentityManager(_MockReidClient())
        mgr4._reid_client.emb = emb_a
        await mgr4.process_frame(frame, [_track(1)])
        for _ in range(3):
            await mgr4.process_frame(frame, [_track(1)])
        await mgr4.process_frame(frame, [])
        r, _, _ = await mgr4.process_frame(frame, [_track(1)])
        assert r[0]["local_id"] == 1
        assert 1 not in mgr4._pending
        print(f"[6] BoTSORT reuse → local_id={r[0]['local_id']} ✓")

        print("\nsmoke test passed")

    asyncio.run(_run_tests())
