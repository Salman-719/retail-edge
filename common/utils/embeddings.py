"""Canonical float32-vector (de)serialization shared by both services and the DB
layer. Guarantees IEP2's writes and IEP3's reads agree on layout regardless of
the active model dimension."""

from __future__ import annotations

import numpy as np


def serialize_embedding(vec: np.ndarray) -> bytes:
    """float32, contiguous, raw bytes."""
    arr = np.ascontiguousarray(vec, dtype=np.float32)
    return arr.tobytes()


def deserialize_embedding(blob: bytes, dim: int | None = None) -> np.ndarray:
    """Inverse of serialize_embedding.

    When ``dim`` is provided, validate the stored vector against the active model.
    When omitted, trust the blob length so old persisted embeddings remain readable
    after switching ReID backends.
    """
    arr = np.frombuffer(blob, dtype=np.float32)
    if dim is not None and arr.shape[0] != dim:
        raise ValueError(f"embedding length {arr.shape[0]} != expected dim {dim}")
    return arr.copy()  # frombuffer is read-only; copy so callers can mutate


def l2_normalize(vec: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """L2-normalize a vector; safe against zero vectors."""
    arr = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    return (arr / max(norm, eps)).astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors. Inputs need not be pre-normalized."""
    return float(np.dot(l2_normalize(a), l2_normalize(b)))
