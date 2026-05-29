"""Diversity-aware embedding gallery.

Combines the spec's add/replace rules with farthest-first diversity: at capacity
a newcomer replaces the *most redundant* entry only if the newcomer is more
novel than that entry. The centroid is recomputed from scratch on replacement
(never EMA after a removal -- M3 review issue B5); below capacity it tracks an
EMA of added vectors.
"""

from __future__ import annotations

import numpy as np

from common.utils.embeddings import cosine_similarity, l2_normalize


class EmbeddingGallery:
    def __init__(self, max_size: int, ema_alpha: float):
        self.embeddings: list[np.ndarray] = []
        self.centroid: np.ndarray | None = None
        self._max = max_size
        self._alpha = ema_alpha

    def add(self, vec: np.ndarray) -> None:
        vec = l2_normalize(vec)
        if len(self.embeddings) < self._max:
            self.embeddings.append(vec)
            self._update_centroid_ema(vec)
        else:
            self._maybe_replace(vec)

    def _update_centroid_ema(self, vec: np.ndarray) -> None:
        if self.centroid is None:
            self.centroid = vec.copy()
        else:
            self.centroid = l2_normalize((1 - self._alpha) * self.centroid + self._alpha * vec)

    def _maybe_replace(self, vec: np.ndarray) -> None:
        """Replace the most redundant entry only if the newcomer is more novel.
        After replacement, recompute the centroid directly from all entries."""
        sims = [cosine_similarity(e, self.centroid) for e in self.embeddings]
        max_idx = int(np.argmax(sims))
        new_sim = cosine_similarity(vec, self.centroid)
        if new_sim >= sims[max_idx]:
            return  # newcomer is more redundant -> discard
        self.embeddings[max_idx] = vec
        self.centroid = l2_normalize(np.mean(self.embeddings, axis=0))

    def snapshot_centroid(self) -> np.ndarray:
        if self.centroid is None:
            raise ValueError("gallery has no centroid yet (no embeddings added)")
        return self.centroid.copy()
