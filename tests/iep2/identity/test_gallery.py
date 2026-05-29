"""EmbeddingGallery: add/EMA below capacity; novelty-based replace at capacity."""

from __future__ import annotations

import numpy as np

from common.utils.embeddings import cosine_similarity, l2_normalize
from services.iep2_vision.app.identity.gallery import EmbeddingGallery


def _onehot(i: int, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    return v


def test_add_below_capacity_grows_and_updates_centroid():
    g = EmbeddingGallery(max_size=4, ema_alpha=0.5)
    g.add(_onehot(0))
    assert len(g.embeddings) == 1
    assert cosine_similarity(g.centroid, _onehot(0)) == 1.0
    g.add(_onehot(1))
    assert len(g.embeddings) == 2
    # centroid moved toward the new vector (EMA), no longer a pure one-hot
    assert g.centroid[0] > 0 and g.centroid[1] > 0


def test_more_novel_embedding_replaces_most_redundant():
    g = EmbeddingGallery(max_size=2, ema_alpha=0.5)
    g.add(_onehot(0))
    g.add(_onehot(0))  # redundant duplicate -> centroid stays at dim 0
    # a novel orthogonal vector should replace one of the redundant entries
    g.add(_onehot(1))
    assert len(g.embeddings) == 2
    sims_to_1 = [cosine_similarity(e, _onehot(1)) for e in g.embeddings]
    assert max(sims_to_1) == 1.0  # the novel vector made it in


def test_more_redundant_embedding_discarded():
    g = EmbeddingGallery(max_size=2, ema_alpha=0.5)
    g.add(_onehot(0))
    g.add(_onehot(1))
    before = [e.copy() for e in g.embeddings]
    # newcomer identical to centroid direction is maximally redundant -> discarded
    g.add(l2_normalize(g.centroid))
    after = g.embeddings
    assert len(after) == 2
    assert all(np.allclose(a, b) for a, b in zip(before, after))


def test_centroid_recomputed_from_scratch_on_replace():
    g = EmbeddingGallery(max_size=2, ema_alpha=0.5)
    g.add(_onehot(0))
    g.add(_onehot(0))
    g.add(_onehot(1))  # triggers replacement
    expected = l2_normalize(np.mean(g.embeddings, axis=0))
    assert np.allclose(g.centroid, expected)
