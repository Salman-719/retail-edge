"""Unit tests for the IEP2 quality embedding store (gallery heap + quality score).

Validates the top-MAX_EMBEDDINGS heap, packed export/load round-trip, and the
per-embedding quality scoring that feeds IEP3 cross-camera matching.
"""
import os
import sys

import numpy as np
import pytest

# Make the IEP2 identity package importable without pip install.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "services", "iep2_vision"),
)

from identity.gallery import EmbeddingGallery, EMBEDDING_DIM, MAX_EMBEDDINGS  # noqa: E402
from identity.manager import _quality_score  # noqa: E402

RNG = np.random.default_rng(0)


def _emb():
    v = RNG.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


# ── heap capacity + eviction ──────────────────────────────────────────────────

def test_heap_caps_at_max():
    g = EmbeddingGallery()
    for i in range(MAX_EMBEDDINGS + 5):
        g.add(_emb(), quality_score=0.5)
    assert len(g) == MAX_EMBEDDINGS


def test_higher_quality_evicts_lowest():
    g = EmbeddingGallery()
    for i in range(MAX_EMBEDDINGS):
        g.add(_emb(), quality_score=0.1 * (i + 1))
    root_before = g._heap[0][0]
    g.add(_emb(), quality_score=0.99)
    assert g._heap[0][0] > root_before
    assert len(g) == MAX_EMBEDDINGS


def test_lower_quality_discarded():
    g = EmbeddingGallery()
    for i in range(MAX_EMBEDDINGS):
        g.add(_emb(), quality_score=0.5 + 0.01 * i)
    embs_before, _, scores_before = g.export_packed()
    g.add(_emb(), quality_score=0.001)  # below every retained score
    embs_after, _, scores_after = g.export_packed()
    assert scores_before == scores_after  # nothing changed


def test_equal_scores_do_not_raise():
    g = EmbeddingGallery()
    for _ in range(MAX_EMBEDDINGS + 3):
        g.add(_emb(), quality_score=0.5)  # ties — must not compare ndarrays
    assert len(g) == MAX_EMBEDDINGS


# ── phase flag ────────────────────────────────────────────────────────────────

def test_phase_flips_on_first_sampled_add():
    g = EmbeddingGallery()
    assert g.is_init_phase
    g.add(_emb(), 0.5, is_init=True)
    assert g.is_init_phase
    g.add(_emb(), 0.5, is_init=False)
    assert not g.is_init_phase


# ── packed export / load ──────────────────────────────────────────────────────

def test_export_packed_shapes_and_order():
    g = EmbeddingGallery()
    for q in [0.2, 0.9, 0.5]:
        g.add(_emb(), quality_score=q)
    embs_b, count, scores_b = g.export_packed()
    assert count == 3
    assert len(embs_b) == 3 * EMBEDDING_DIM * 4
    assert len(scores_b) == 3 * 4
    scores = np.frombuffer(scores_b, dtype=np.float32)
    assert list(scores) == sorted(scores, reverse=True)  # descending quality
    assert scores[0] == pytest.approx(0.9)


def test_empty_gallery_exports_none():
    assert EmbeddingGallery().export_packed() is None
    assert EmbeddingGallery().snapshot_centroid() is None


def test_load_packed_round_trip():
    g = EmbeddingGallery()
    for q in np.linspace(0.1, 0.95, MAX_EMBEDDINGS):
        g.add(_emb(), quality_score=float(q))
    embs_b, count, scores_b = g.export_packed()

    g2 = EmbeddingGallery()
    g2.load_packed(embs_b, count, scores_b)
    e2, c2, s2 = g2.export_packed()
    assert (e2, c2, s2) == (embs_b, count, scores_b)
    assert not g2.is_init_phase


def test_load_packed_empty_is_noop():
    g = EmbeddingGallery()
    g.load_packed(b"", 0, b"")
    assert len(g) == 0


# ── centroid ──────────────────────────────────────────────────────────────────

def test_snapshot_centroid_is_l2_normalized():
    g = EmbeddingGallery()
    for _ in range(4):
        g.add(_emb(), quality_score=0.5)
    c = g.snapshot_centroid()
    assert c.shape == (EMBEDDING_DIM,)
    assert float(np.linalg.norm(c)) == pytest.approx(1.0, abs=1e-5)


# ── quality score ─────────────────────────────────────────────────────────────

def test_quality_score_formula():
    # conf 0.8, bbox height 100, frame height 200 → 0.8 * 0.5 = 0.4
    assert _quality_score(0.8, [0, 50, 10, 150], 200) == pytest.approx(0.4)


def test_quality_score_clamped_and_guarded():
    assert _quality_score(0.9, [0, 0, 10, 10], 0) == 0.0          # zero frame height
    assert _quality_score(1.0, [0, 0, 10, 9999], 100) == 1.0      # clamp to 1.0
    assert _quality_score(0.5, [0, 100, 10, 50], 200) == 0.0      # negative height → 0
