"""LocalIdentityManager — stable Local ID assignment with occlusion recovery.

Lifecycle:
  new track (lost pool empty)  → fast path → ActiveTrack immediately
  new track (lost pool non-empty) → PendingTrack → collect init embeddings
                                    → ReID against lost pool → recover or mint
  disappeared active track     → LostEntry (with gallery, TTL)
  disappeared pending track    → dropped silently (no local_id ever minted)
"""
import numpy as np

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

        for tid in disappeared_pending:
            del self._pending[tid]  # dropped silently — no local_id ever minted

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
                    enriched.append({**track, "local_id": None})

            # ── Branch C: first appearance ─────────────────────────────────────
            else:
                if not self._lost:
                    # Fast path — no occlusion candidates, assign immediately
                    local_id = self._next_id
                    self._next_id += 1
                    gallery = EmbeddingGallery()
                    self._active[tid] = ActiveTrack(
                        local_id=local_id, track_id=tid, gallery=gallery
                    )
                    enriched.append({**track, "local_id": local_id})
                else:
                    # Normal path — may be a re-entry; hold in pending
                    self._pending[tid] = PendingTrack(track_id=tid)
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
        else:
            # Stranger — mint new identity
            local_id = self._next_id
            self._next_id += 1
            gallery = EmbeddingGallery()

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

    # ── Test 5: TTL expiry → lost entry pruned → reappear gets new local_id ───
    mgr3  = LocalIdentityManager(mock)
    mock.emb = emb_a
    mgr3.process_frame(frame, [_track(1)])         # local_id=1, fast path
    mgr3.process_frame(frame, [])                  # → lost

    for _ in range(TTL_FRAMES + 1):                # burn past TTL
        mgr3.process_frame(frame, [])

    assert len(mgr3._lost) == 0, "TTL-expired entry must be pruned"

    r = mgr3.process_frame(frame, [_track(1)])     # lost pool empty → fast path
    assert r[0]["local_id"] is not None
    # local_id=1 was already used; _next_id is now 2 → new assignment is 2
    assert r[0]["local_id"] != 1, "after TTL, new local_id must be minted (no reuse)"
    print(f"[5] TTL expiry → new local_id={r[0]['local_id']} minted ✓")

    print("\nsmoke test passed")
