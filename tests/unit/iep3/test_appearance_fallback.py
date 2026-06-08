"""Unit tests for Stage 3 appearance fallback."""
import uuid

import numpy as np

from app.appearance_fallback import resolve_ambiguous

A1 = uuid.UUID(int=1)
B1 = uuid.UUID(int=101)
B2 = uuid.UUID(int=102)


def _cluster(direction_seed, n=5, dim=8, noise=0.02):
    """A stack of n near-parallel unit vectors (one person's gallery).

    Same direction_seed → high cross-stack median cosine; different seed →
    near-orthogonal (low). Mirrors how a real person's embeddings cluster.
    """
    rng = np.random.default_rng(direction_seed)
    base = rng.standard_normal(dim)
    base = base / np.linalg.norm(base)
    rows = base + noise * rng.standard_normal((n, dim))
    return (rows / np.linalg.norm(rows, axis=1, keepdims=True)).astype(np.float32)


def test_high_appearance_confirms():
    embeddings = {A1: _cluster(1), B1: _cluster(1)}  # same direction → median cosine ≈ 1
    # vote_rate 0.5 → final ≈ 0.5*0.7 + 1.0*0.3 = 0.65 ≥ 0.55
    confirmed = resolve_ambiguous(
        [(A1, B1, 0.5)], embeddings, reid_fallback_threshold=0.55
    )
    assert confirmed == {(A1, B1, 0.5)}


def test_low_appearance_rejects():
    a = _cluster(1)
    embeddings = {A1: a, B1: -a}  # opposite direction → cosine ≈ -1
    # final ≈ 0.5*0.7 + (-1)*0.3 = 0.05 < 0.55
    confirmed = resolve_ambiguous(
        [(A1, B1, 0.5)], embeddings, reid_fallback_threshold=0.55
    )
    assert confirmed == set()


def test_picks_best_candidate():
    embeddings = {A1: _cluster(1), B1: _cluster(1), B2: _cluster(99)}  # B1 matches A1
    confirmed = resolve_ambiguous(
        [(A1, B1, 0.5), (A1, B2, 0.5)], embeddings, reid_fallback_threshold=0.55
    )
    assert confirmed == {(A1, B1, 0.5)}


def test_missing_embedding_uses_zero_appearance():
    embeddings = {A1: _cluster(1)}  # B1 absent
    # final = 0.9*0.7 + 0*0.3 = 0.63 ≥ 0.55 (spatial alone strong enough)
    confirmed = resolve_ambiguous(
        [(A1, B1, 0.9)], embeddings, reid_fallback_threshold=0.55
    )
    assert confirmed == {(A1, B1, 0.9)}


def test_at_most_one_per_local_a():
    embeddings = {A1: _cluster(1), B1: _cluster(1), B2: _cluster(1)}
    confirmed = resolve_ambiguous(
        [(A1, B1, 0.6), (A1, B2, 0.5)], embeddings, reid_fallback_threshold=0.55
    )
    assert len(confirmed) == 1
    assert next(iter(confirmed))[0] == A1
