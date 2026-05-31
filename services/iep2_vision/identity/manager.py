"""LocalIdentityManager — stable Local ID assignment with occlusion recovery.

Lifecycle:
  new track (lost pool empty)  → fast path → ActiveTrack immediately
  new track (lost pool non-empty) → PendingTrack → collect init embeddings
                                    → ReID against lost pool → recover or mint
  disappeared active track     → LostEntry (with gallery, TTL)
  disappeared pending track    → dropped silently (no local_id ever minted)
"""
import logging

import numpy as np

log = logging.getLogger("iep2.identity")

try:
    from ..reid.reid import extract_embedding
    from .pools import ActiveTrack, PendingTrack, LostEntry
    from .gallery import EmbeddingGallery
except ImportError:
    import sys as _sys, os as _os
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path.insert(0, _os.path.join(_here, ".."))  # exposes reid/reid.py
    _sys.path.insert(0, _here)                        # exposes pools.py, gallery.py
    from reid.reid import extract_embedding
    from pools import ActiveTrack, PendingTrack, LostEntry
    from gallery import EmbeddingGallery

# ── Constants (single source of truth) ────────────────────────────────────────
TTL_FRAMES                 = 150   # 30 s at 5 fps
INIT_EMBEDDINGS_COUNT      = 5     # embeddings collected before ReID attempt
REID_THRESHOLD             = 0.75  # cosine similarity threshold for a match
SAMPLE_INTERVAL            = 15    # frames between samples in sampled phase
QUALITY_CONFIDENCE_THRESHOLD = 0.6 # minimum YOLO conf for sampled-phase sample
MIN_BBOX_AREA              = 2500  # minimum bbox area (px²) for sampled-phase sample


class LocalIdentityManager:
    def __init__(self, reid_model):
        """reid_model is the object returned by reid.load_model(); injected once."""
        self._reid_model = reid_model
        self._active:  dict[int, ActiveTrack]  = {}  # track_id  → ActiveTrack
        self._pending: dict[int, PendingTrack] = {}  # track_id  → PendingTrack
        self._lost:    dict[int, LostEntry]    = {}  # local_id  → LostEntry
        # Sticky mapping: once a track_id is assigned a local_id, the binding is permanent.
        # When ByteTrack re-surfaces the same track_id, we restore the prior local_id
        # immediately without going through pending/ReID, because ByteTrack already
        # confirmed it is the same physical object.
        self._track_to_local: dict[int, int] = {}    # track_id  → local_id (immutable)
        self._next_id: int = 1
        self._frame_index: int = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray, tracks: list[dict]) -> list[dict]:
        """Run the full identity lifecycle for one frame.

        Returns a new list of enriched dicts with 'local_id' added.
        Active tracks carry an int local_id; pending tracks carry None.
        Input list is never mutated.
        """
        # Stage 0 — advance frame counter
        self._frame_index += 1

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
            )
            log.info(
                "F%04d  track disappeared  track_id=%d  local_id=%d  → lost pool (TTL=%d frames)",
                self._frame_index, tid, entry.local_id, TTL_FRAMES,
            )

        for tid in disappeared_pending:
            del self._pending[tid]  # dropped silently — no local_id ever minted
            log.info("F%04d  pending track dropped  track_id=%d  (never resolved)", self._frame_index, tid)

        # Stage 3 — process each current track
        enriched: list[dict] = []
        for track in tracks:
            tid = track["track_id"]

            # ── Branch A: already active ───────────────────────────────────────
            if tid in self._active:
                active = self._active[tid]
                gallery = active.gallery

                if gallery.is_init_phase:
                    emb = extract_embedding(self._reid_model, frame, track["bbox"])
                    if emb is not None:
                        gallery.add(emb, is_init=True)
                else:
                    # Sampled phase: quality-gated, interval-throttled
                    if self._frame_index % SAMPLE_INTERVAL == 0:
                        conf = track.get("confidence", 0.0)
                        x1, y1, x2, y2 = track["bbox"]
                        bbox_area = (x2 - x1) * (y2 - y1)
                        if (conf >= QUALITY_CONFIDENCE_THRESHOLD
                                and bbox_area >= MIN_BBOX_AREA):
                            emb = extract_embedding(self._reid_model, frame, track["bbox"])
                            if emb is not None:
                                gallery.add(emb, is_init=False)

                enriched.append({**track, "local_id": active.local_id})

            # ── Branch B: pending, collecting init embeddings ──────────────────
            elif tid in self._pending:
                pending = self._pending[tid]
                emb = extract_embedding(self._reid_model, frame, track["bbox"])
                if emb is not None:
                    pending.init_embeddings.append(emb)

                if len(pending.init_embeddings) >= INIT_EMBEDDINGS_COUNT:
                    local_id, gallery = self._resolve_pending(pending)
                    self._active[tid] = ActiveTrack(
                        local_id=local_id, track_id=tid, gallery=gallery
                    )
                    del self._pending[tid]
                    enriched.append({**track, "local_id": local_id})
                else:
                    log.debug(
                        "F%04d  collecting  track_id=%d  embeddings=%d/%d",
                        self._frame_index, tid, len(pending.init_embeddings), INIT_EMBEDDINGS_COUNT,
                    )
                    enriched.append({**track, "local_id": None})

            # ── Branch C: first appearance ─────────────────────────────────────
            else:
                if tid in self._track_to_local:
                    # ByteTrack re-surfaced a known track_id — this is the same physical
                    # object, so restore the prior local_id immediately without pending/ReID.
                    local_id = self._track_to_local[tid]
                    if local_id in self._lost:
                        lost_entry = self._lost.pop(local_id)
                        gallery = lost_entry.gallery
                        log.info(
                            "F%04d  ByteTrack reuse  track_id=%d  → local_id=%d  (restored from lost pool)",
                            self._frame_index, tid, local_id,
                        )
                    else:
                        # TTL already expired but ByteTrack kept the id alive — start fresh gallery
                        gallery = EmbeddingGallery()
                        log.info(
                            "F%04d  ByteTrack reuse (post-TTL)  track_id=%d  → local_id=%d  (fresh gallery)",
                            self._frame_index, tid, local_id,
                        )
                    self._active[tid] = ActiveTrack(local_id=local_id, track_id=tid, gallery=gallery)
                    enriched.append({**track, "local_id": local_id})

                elif not self._lost:
                    # Fast path — no occlusion candidates, assign immediately
                    local_id = self._next_id
                    self._next_id += 1
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

        return enriched

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _resolve_pending(self, pending: PendingTrack):
        """Match pending init embeddings against the lost pool.

        Returns (local_id, gallery): either a recovered pair or a freshly minted one.
        """
        mean_emb = np.mean(pending.init_embeddings, axis=0).astype(np.float32)
        norm = np.linalg.norm(mean_emb)
        if norm > 0:
            mean_emb = mean_emb / norm

        best_sim = -1.0
        best_lid = None
        for lid, lost_entry in self._lost.items():
            centroid = lost_entry.gallery.snapshot_centroid()
            if centroid is None:
                continue
            sim = float(np.dot(mean_emb, centroid))
            if sim > best_sim:
                best_sim = sim
                best_lid = lid

        if best_lid is not None and best_sim >= REID_THRESHOLD:
            # Recover lost identity
            lost_entry = self._lost.pop(best_lid)
            local_id = lost_entry.local_id
            gallery = lost_entry.gallery
            self._track_to_local[pending.track_id] = local_id
            log.info(
                "F%04d  ReID MATCH  track_id=%d  → local_id=%d  sim=%.3f  (threshold=%.2f)",
                self._frame_index, pending.track_id, local_id, best_sim, REID_THRESHOLD,
            )
        else:
            # Stranger — mint new identity
            local_id = self._next_id
            self._next_id += 1
            gallery = EmbeddingGallery()
            self._track_to_local[pending.track_id] = local_id
            log.info(
                "F%04d  ReID NO MATCH  track_id=%d  → new local_id=%d  best_sim=%.3f  (threshold=%.2f)",
                self._frame_index, pending.track_id, local_id,
                best_sim if best_lid is not None else 0.0, REID_THRESHOLD,
            )

        # Seed gallery with the collected init embeddings (already L2-normalized)
        for emb in pending.init_embeddings:
            gallery.add(emb, is_init=True)

        return local_id, gallery


# ---------------------------------------------------------------------------
# Standalone smoke test: python identity/manager.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    class _MockModel:
        """Injects a controlled embedding regardless of frame content."""
        def __init__(self):
            self.emb = np.zeros(512, dtype=np.float32)

        def get_features(self, crops):
            return np.array([self.emb], dtype=np.float32)

    mock = _MockModel()
    mgr  = LocalIdentityManager(mock)

    emb_a = np.zeros(512, dtype=np.float32); emb_a[0] = 1.0  # [1,0,0,...]
    emb_b = np.zeros(512, dtype=np.float32); emb_b[1] = 1.0  # [0,1,0,...] orthogonal to A

    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    bbox  = [10, 10, 110, 160]  # 100×150 px, area=15 000 > MIN_BBOX_AREA

    def _track(tid):
        return {"track_id": tid, "label": "person", "confidence": 0.9, "bbox": bbox}

    # ── Test 1: fast path (lost pool empty) ───────────────────────────────────
    mock.emb = emb_a
    r = mgr.process_frame(frame, [_track(1)])
    local_id_a = r[0]["local_id"]
    assert local_id_a == 1, f"fast path: expected local_id=1, got {local_id_a}"

    for _ in range(3):           # keep track 1 active a few frames
        mgr.process_frame(frame, [_track(1)])

    mgr.process_frame(frame, []) # track 1 disappears → enters lost pool
    assert 1 in mgr._lost, "local_id 1 should be in lost pool"
    print(f"[1] fast path + disappear → lost pool ✓  (local_id={local_id_a})")

    # ── Test 2: orthogonal person gets a new local_id ─────────────────────────
    mock.emb = emb_b
    r = mgr.process_frame(frame, [_track(2)])      # Branch C → pending
    assert r[0]["local_id"] is None

    for _ in range(INIT_EMBEDDINGS_COUNT - 1):     # collect 4 more (pending)
        r = mgr.process_frame(frame, [_track(2)])
        assert r[0]["local_id"] is None, "should still be pending"

    r = mgr.process_frame(frame, [_track(2)])      # 5th embedding → resolve
    local_id_b = r[0]["local_id"]
    assert local_id_b is not None
    assert local_id_b != local_id_a, (
        f"orthogonal person must get new local_id, got {local_id_b} vs {local_id_a}"
    )
    print(f"[2] orthogonal person → new local_id={local_id_b} ✓")

    mgr.process_frame(frame, [])  # track 2 disappears (goes to lost too)

    # ── Test 3: same person recovers local_id after occlusion ─────────────────
    # Lost pool now has both A (local_id=1) and B (local_id=2).
    mock.emb = emb_a
    r = mgr.process_frame(frame, [_track(3)])      # Branch C → pending
    assert r[0]["local_id"] is None

    for _ in range(INIT_EMBEDDINGS_COUNT - 1):
        r = mgr.process_frame(frame, [_track(3)])
        assert r[0]["local_id"] is None

    r = mgr.process_frame(frame, [_track(3)])      # resolve → must match A
    recovered_id = r[0]["local_id"]
    assert recovered_id == local_id_a, (
        f"same person must recover local_id={local_id_a}, got {recovered_id}"
    )
    print(f"[3] ReID recovery → local_id={recovered_id} == original {local_id_a} ✓")

    # ── Test 4: pending track disappears before resolving → no lost entry ──────
    mgr2  = LocalIdentityManager(mock)
    mock.emb = emb_a
    mgr2.process_frame(frame, [_track(1)])         # fast path → active
    mgr2.process_frame(frame, [])                  # disappears → lost

    mgr2.process_frame(frame, [_track(99)])        # Branch C → pending
    assert 99 in mgr2._pending

    mgr2.process_frame(frame, [])                  # track 99 disappears mid-pending
    assert 99 not in mgr2._pending, "pending track must be dropped"
    assert all(e.local_id != 99 for e in mgr2._lost.values()), (
        "dropped pending track must not create a lost entry"
    )
    print("[4] pending disappear → silently dropped, no lost entry ✓")

    # ── Test 5: TTL expiry → sticky mapping still restores the same local_id ──
    mgr3  = LocalIdentityManager(mock)
    mock.emb = emb_a
    mgr3.process_frame(frame, [_track(1)])         # local_id=1, fast path
    mgr3.process_frame(frame, [])                  # → lost

    for _ in range(TTL_FRAMES + 1):                # burn past TTL
        mgr3.process_frame(frame, [])

    assert len(mgr3._lost) == 0, "TTL-expired entry must be pruned"

    r = mgr3.process_frame(frame, [_track(1)])     # sticky mapping restores local_id=1
    assert r[0]["local_id"] == 1, (
        f"sticky mapping must restore local_id=1 even after TTL, got {r[0]['local_id']}"
    )
    print(f"[5] TTL expiry + sticky mapping → local_id={r[0]['local_id']} restored ✓")

    # ── Test 6: ByteTrack reuse across 1-frame gap (the reported bug scenario) ──
    # Person active as track_id=1/local_id=1 → disappears 1 frame →
    # ByteTrack re-surfaces track_id=1 → must immediately get local_id=1 back,
    # NOT go through pending/ReID.
    mgr4  = LocalIdentityManager(mock)
    mock.emb = emb_a
    mgr4.process_frame(frame, [_track(1)])         # fast path → local_id=1
    for _ in range(3):
        mgr4.process_frame(frame, [_track(1)])     # keep active
    mgr4.process_frame(frame, [])                  # disappears → lost pool
    assert 1 in mgr4._lost, "local_id=1 should be in lost pool"

    r = mgr4.process_frame(frame, [_track(1)])     # ByteTrack re-surfaces same track_id
    assert r[0]["local_id"] == 1, (
        f"ByteTrack reuse must restore local_id=1 immediately, got {r[0]['local_id']}"
    )
    assert 1 not in mgr4._pending, "must NOT go through pending on ByteTrack reuse"
    assert 1 not in mgr4._lost,    "must be removed from lost pool on reuse"
    print(f"[6] ByteTrack 1-frame gap → local_id={r[0]['local_id']} restored instantly ✓")

    print("\nsmoke test passed")
