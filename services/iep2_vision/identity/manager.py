"""LocalIdentityManager — stable Local ID assignment per track per session.

ByteTrack IDs are ephemeral; this manager wraps them with a persistent
integer Local ID for the lifetime of a session. Active pool only — no Lost
pool, no ReID. Steps 4 and 5 extend this without touching pools.py.
"""
import numpy as np

from .pools import ActiveTrack


class LocalIdentityManager:
    def __init__(self):
        self._active: dict[int, ActiveTrack] = {}  # track_id -> ActiveTrack
        self._next_id: int = 1

    def process_frame(self, frame: np.ndarray, tracks: list[dict]) -> list[dict]:
        """Assign stable Local IDs to each track in the current frame.

        frame: received for API compatibility with Step 4 — not used here.
        tracks: list of dicts with at least {"track_id": int, ...}.
        Returns a new list of dicts with "local_id" added; input is not mutated.
        """
        current_track_ids = {t["track_id"] for t in tracks}

        # Drop disappeared tracks — silent, no Lost pool in this step.
        disappeared = [tid for tid in self._active if tid not in current_track_ids]
        for tid in disappeared:
            del self._active[tid]

        enriched: list[dict] = []
        for track in tracks:
            tid = track["track_id"]
            if tid not in self._active:
                self._active[tid] = ActiveTrack(local_id=self._next_id, track_id=tid)
                self._next_id += 1
            local_id = self._active[tid].local_id
            enriched.append({**track, "local_id": local_id})

        return enriched


# ---------------------------------------------------------------------------
# Standalone smoke test: python identity/manager.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    mgr = LocalIdentityManager()

    frames = [
        # Frame 0: tracks 10, 20
        [{"track_id": 10, "label": "person", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
         {"track_id": 20, "label": "person", "confidence": 0.8, "bbox": [5, 5, 15, 15]}],
        # Frame 1: track 10 stays, 20 disappears, 30 arrives
        [{"track_id": 10, "label": "person", "confidence": 0.9, "bbox": [1, 1, 11, 11]},
         {"track_id": 30, "label": "person", "confidence": 0.7, "bbox": [20, 20, 30, 30]}],
        # Frame 2: track 10 stays, 20 reappears (must get a new local_id)
        [{"track_id": 10, "label": "person", "confidence": 0.9, "bbox": [2, 2, 12, 12]},
         {"track_id": 20, "label": "person", "confidence": 0.85, "bbox": [6, 6, 16, 16]}],
    ]

    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    results = []
    for f in frames:
        results.append(mgr.process_frame(dummy_frame, f))

    for i, frame_result in enumerate(results):
        print(f"frame {i}: {json.dumps(frame_result, indent=2)}")

    # Assertions
    f0 = {t["track_id"]: t["local_id"] for t in results[0]}
    f1 = {t["track_id"]: t["local_id"] for t in results[1]}
    f2 = {t["track_id"]: t["local_id"] for t in results[2]}

    assert f0[10] == f1[10] == f2[10], "track 10 must always get the same local_id"
    assert f1[30] != f0[10], "new track must get a new local_id"
    assert f2[20] != f0[20], "reappeared track must get a new local_id (no reuse)"
    assert len({f0[10], f0[20], f1[30], f2[20]}) == 4, "_next_id must never reuse"

    print("smoke test passed")
