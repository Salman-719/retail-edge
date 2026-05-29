"""Foundation tests for common.utils.embeddings."""

from __future__ import annotations

import numpy as np
import pytest

from common.utils.embeddings import (
    cosine_similarity,
    deserialize_embedding,
    l2_normalize,
    serialize_embedding,
)


def test_round_trip_preserves_values():
    vec = np.array([0.1, -0.2, 0.3, 0.4], dtype=np.float32)
    blob = serialize_embedding(vec)
    out = deserialize_embedding(blob, dim=4)
    np.testing.assert_allclose(out, vec, rtol=0, atol=1e-7)


def test_deserialize_dimension_mismatch_raises():
    blob = serialize_embedding(np.ones(8, dtype=np.float32))
    with pytest.raises(ValueError):
        deserialize_embedding(blob, dim=512)


def test_deserialized_array_is_writable():
    out = deserialize_embedding(serialize_embedding(np.ones(3, dtype=np.float32)), dim=3)
    out[0] = 5.0  # must not raise (frombuffer is read-only; we copy)
    assert out[0] == 5.0


def test_l2_normalize_zero_vector_safe():
    out = l2_normalize(np.zeros(16, dtype=np.float32))
    assert np.all(np.isfinite(out))
    assert np.linalg.norm(out) == pytest.approx(0.0)


def test_cosine_identical_is_one():
    vec = np.array([3.0, 4.0, 0.0], dtype=np.float32)
    assert cosine_similarity(vec, vec) == pytest.approx(1.0, abs=1e-6)


def test_cosine_different_below_one():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)
