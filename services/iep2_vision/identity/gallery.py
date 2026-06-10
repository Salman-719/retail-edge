"""EmbeddingGallery — bounded top-quality embedding store per person.

Maintains a min-heap of up to MAX_EMBEDDINGS ``(quality_score, embedding)``
pairs. The lowest-quality embedding sits at the heap root and is evicted first
when a higher-quality one arrives at capacity. Two consumers:

  * ``snapshot_centroid()`` — L2-normalized mean of the retained embeddings,
    computed on demand for IEP2's *internal* occlusion-recovery ReID
    (LocalIdentityManager._resolve_pending). Never persisted.
  * ``export_packed()`` — the raw embeddings + their quality scores, written to
    ``local_centroids`` at batch end for IEP3 cross-camera matching.

This replaces the previous EMA-centroid gallery: IEP3 now matches against the
raw top-quality embeddings (median cosine), so IEP2 keeps them instead of
smearing them into a single running mean. No ReID logic, no pool logic — pure
storage + math.
"""
import heapq
import itertools

import numpy as np

EMBEDDING_DIM  = 2048   # resnet50_msmt17 output
MAX_EMBEDDINGS = 10     # heap capacity per local_id (matches IEP3 MAX_EMBEDDINGS)


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


class EmbeddingGallery:
    def __init__(self, max_size: int = MAX_EMBEDDINGS):
        self._max_size = max_size
        # Min-heap of (quality_score, seq, embedding). `seq` is a strictly
        # increasing tiebreaker so two equal quality scores never fall through
        # to comparing numpy arrays (which raises ValueError).
        self._heap: list[tuple[float, int, np.ndarray]] = []
        self._seq = itertools.count()
        self._is_init_phase: bool = True

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add(self, embedding: np.ndarray, quality_score: float, is_init: bool = False) -> None:
        """Insert an already-L2-normalized embedding with its quality score.

        ``is_init`` only tracks the init→sampled phase transition that the
        manager reads to gate buffering vs sampling; both phases feed the same
        quality heap (unlike the old gallery, init embeddings are not discarded
        on phase switch — they compete on quality like any other).
        """
        if not is_init and self._is_init_phase:
            self._is_init_phase = False
        self._push(float(quality_score), embedding)

    def _push(self, quality_score: float, embedding: np.ndarray) -> None:
        item = (quality_score, next(self._seq), embedding)
        if len(self._heap) < self._max_size:
            heapq.heappush(self._heap, item)
        elif quality_score > self._heap[0][0]:
            heapq.heapreplace(self._heap, item)
        # else: lower quality than every retained embedding — discard.

    @property
    def is_init_phase(self) -> bool:
        return self._is_init_phase

    def __len__(self) -> int:
        return len(self._heap)

    def snapshot_centroid(self) -> np.ndarray | None:
        """L2-normalized mean of retained embeddings, or None if empty.

        Read-only — never mutates heap state. Used only for IEP2-internal
        occlusion-recovery ReID, never stored.
        """
        if not self._heap:
            return None
        mean = np.mean([e for _, _, e in self._heap], axis=0)
        norm = np.linalg.norm(mean)
        if norm == 0:
            return None
        return (mean / norm).astype(np.float32)

    def export_packed(self) -> tuple[bytes, int, bytes] | None:
        """Pack the heap for local_centroids.

        Returns ``(embeddings_bytes, embedding_count, quality_scores_bytes)``
        ordered by descending quality, where embeddings_bytes is
        ``count * EMBEDDING_DIM`` float32 and quality_scores_bytes is ``count``
        float32. Returns None when the heap is empty (caller skips the upsert).
        """
        if not self._heap:
            return None
        ordered = sorted(self._heap, key=lambda t: t[0], reverse=True)
        embs   = np.array([e for _, _, e in ordered], dtype=np.float32)
        scores = np.array([q for q, _, _ in ordered], dtype=np.float32)
        return embs.tobytes(), len(ordered), scores.tobytes()

    def load_packed(
        self,
        embeddings_bytes: bytes,
        embedding_count: int,
        quality_scores_bytes: bytes,
    ) -> None:
        """Rebuild the heap from a persisted local_centroids row (restart recovery).

        Unpacks ``embeddings_bytes`` into (count, EMBEDDING_DIM) and pairs each
        row with its quality score. Replaces any current heap contents.
        """
        if embedding_count <= 0 or not embeddings_bytes:
            return
        embs = (
            np.frombuffer(embeddings_bytes, dtype=np.float32)
            .reshape(embedding_count, EMBEDDING_DIM)
            .copy()
        )
        scores = np.frombuffer(quality_scores_bytes, dtype=np.float32)
        self._heap = [
            (float(scores[i]) if i < len(scores) else 0.0, next(self._seq), embs[i])
            for i in range(embedding_count)
        ]
        heapq.heapify(self._heap)
        self._is_init_phase = False  # a restored gallery is past its init phase


# ---------------------------------------------------------------------------
# Standalone smoke test: python identity/gallery.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(42)

    def fake_emb():
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        return v / np.linalg.norm(v)

    g = EmbeddingGallery()

    # Fill to capacity with ascending quality.
    for i in range(MAX_EMBEDDINGS):
        g.add(fake_emb(), quality_score=0.1 * (i + 1), is_init=(i < 3))
    assert len(g) == MAX_EMBEDDINGS, "heap should be at capacity"
    assert not g.is_init_phase, "any non-init add flips the phase"

    # A higher-quality embedding evicts the lowest (root).
    low_root = g._heap[0][0]
    g.add(fake_emb(), quality_score=0.95)
    assert g._heap[0][0] > low_root, "root should rise after eviction"
    assert len(g) == MAX_EMBEDDINGS, "size stays capped"

    # A lower-quality embedding is discarded.
    g.add(fake_emb(), quality_score=0.001)
    assert len(g) == MAX_EMBEDDINGS

    # Centroid is L2-normalized.
    c = g.snapshot_centroid()
    assert c is not None and c.shape == (EMBEDDING_DIM,)
    assert abs(float(np.linalg.norm(c)) - 1.0) < 1e-5

    # export → load round-trips identically.
    embs_b, count, scores_b = g.export_packed()
    assert count == MAX_EMBEDDINGS
    assert len(embs_b) == count * EMBEDDING_DIM * 4
    assert len(scores_b) == count * 4
    g2 = EmbeddingGallery()
    g2.load_packed(embs_b, count, scores_b)
    e2, c2, s2 = g2.export_packed()
    assert e2 == embs_b and c2 == count and s2 == scores_b, "round-trip mismatch"

    # Equal quality scores must not raise (tiebreaker works).
    g3 = EmbeddingGallery()
    for _ in range(MAX_EMBEDDINGS + 2):
        g3.add(fake_emb(), quality_score=0.5)
    assert len(g3) == MAX_EMBEDDINGS

    # Empty gallery.
    empty = EmbeddingGallery()
    assert empty.snapshot_centroid() is None
    assert empty.export_packed() is None

    print("smoke test passed")
