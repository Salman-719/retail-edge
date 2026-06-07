"""EmbeddingGallery — bounded, self-managing embedding store per person.

Handles two phases:
  init    — placeholder embeddings collected on track birth, centroid via EMA
  sampled — quality embeddings; phase switch clears all init, diversity kept
             via novelty-based replacement at capacity

No ReID logic, no pool logic — pure math.
"""
import os

import numpy as np

DEFAULT_MAX_SIZE  = 8
# R7 (M2-S4): EMA alpha 0.3 — responsive to appearance change while retaining history.
# Configurable via CENTROID_EMA_ALPHA env var; override for calibration in specific environments.
DEFAULT_EMA_ALPHA = float(os.environ.get("CENTROID_EMA_ALPHA", "0.3"))


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


class EmbeddingGallery:
    def __init__(self, max_size: int = DEFAULT_MAX_SIZE, ema_alpha: float = DEFAULT_EMA_ALPHA):
        self._max_size = max_size
        self._ema_alpha = ema_alpha
        self._embeddings: list[np.ndarray] = []
        self._centroid: np.ndarray | None = None
        self._is_init_phase: bool = True

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add(self, embedding: np.ndarray, is_init: bool) -> None:
        """Add an already-L2-normalized embedding to the gallery.

        is_init=True  → init-phase embedding (e.g. from track birth frame)
        is_init=False → quality sampled embedding
        """
        if is_init and self._is_init_phase:
            self._embeddings.append(embedding)
            self._ema_update_centroid(embedding)
            return

        if not is_init and self._is_init_phase:
            # Phase switch: discard all init embeddings, reset centroid.
            self._embeddings.clear()
            self._centroid = None
            self._is_init_phase = False
            # Fall through to add as first sampled embedding.

        # Sampled phase — below capacity: append + EMA update.
        if len(self._embeddings) < self._max_size:
            self._embeddings.append(embedding)
            self._ema_update_centroid(embedding)
            return

        # Sampled phase — at capacity: novelty-based replacement.
        most_redundant_idx = int(np.argmax(
            [float(np.dot(e, self._centroid)) for e in self._embeddings]
        ))
        redundant_sim = float(np.dot(self._embeddings[most_redundant_idx], self._centroid))
        newcomer_sim = float(np.dot(embedding, self._centroid))

        if newcomer_sim < redundant_sim:
            self._embeddings[most_redundant_idx] = embedding
            self._recompute_centroid()
        # Otherwise discard silently.

    @property
    def is_init_phase(self) -> bool:
        return self._is_init_phase

    def snapshot_centroid(self) -> np.ndarray | None:
        """Return the current L2-normalized centroid, or None if gallery is empty."""
        return self._centroid

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ema_update_centroid(self, new_vec: np.ndarray) -> None:
        if self._centroid is None:
            self._centroid = new_vec.copy()
        else:
            blended = self._ema_alpha * new_vec + (1.0 - self._ema_alpha) * self._centroid
            self._centroid = _l2_normalize(blended)

    def _recompute_centroid(self) -> None:
        if not self._embeddings:
            self._centroid = None
            return
        mean = np.mean(self._embeddings, axis=0)
        self._centroid = _l2_normalize(mean)


# ---------------------------------------------------------------------------
# Standalone smoke test: python identity/gallery.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(42)

    def fake_emb():
        v = rng.standard_normal(2048).astype(np.float32)
        return v / np.linalg.norm(v)

    g = EmbeddingGallery()

    # Add 3 init embeddings.
    for _ in range(3):
        g.add(fake_emb(), is_init=True)
    assert g._is_init_phase, "should still be in init phase"
    assert len(g._embeddings) == 3

    # Add 1 sampled embedding — triggers phase switch.
    g.add(fake_emb(), is_init=False)
    assert not g._is_init_phase, "should have switched to sampled phase"
    assert len(g._embeddings) == 1, "init embeddings should have been cleared"

    c = g.snapshot_centroid()
    assert c is not None
    assert c.shape == (2048,), f"expected (2048,), got {c.shape}"
    norm = float(np.linalg.norm(c))
    assert abs(norm - 1.0) < 1e-5, f"centroid norm should be ~1.0, got {norm:.6f}"

    print(f"centroid shape: {c.shape}")
    print(f"centroid norm:  {norm:.6f}")

    # Fill to capacity and test novelty replacement.
    for _ in range(DEFAULT_MAX_SIZE - 1):
        g.add(fake_emb(), is_init=False)
    assert len(g._embeddings) == DEFAULT_MAX_SIZE

    before = g.snapshot_centroid().copy()
    g.add(fake_emb(), is_init=False)  # at capacity — should replace or discard
    assert len(g._embeddings) == DEFAULT_MAX_SIZE, "size must stay at max_size"

    # snapshot_centroid must be read-only — call twice and compare.
    c1 = g.snapshot_centroid()
    c2 = g.snapshot_centroid()
    assert np.array_equal(c1, c2), "snapshot_centroid must not mutate state"

    # Empty gallery returns None.
    empty = EmbeddingGallery()
    assert empty.snapshot_centroid() is None

    print("smoke test passed")
