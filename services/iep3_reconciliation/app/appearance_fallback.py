"""Stage 3 — appearance fallback for spatially-ambiguous pairs.

Fires only for pairs the spatial voter (Stage 2) marked ambiguous — i.e. pairs
that already have spatial co-visibility evidence but where position alone cannot
decide. For each ambiguous local_a, the candidate local_b with the highest
combined score is confirmed when that score clears REID_FALLBACK_THRESHOLD:

    final_score = vote_rate * 0.7 + appearance_score * 0.3

where appearance_score is the median of the pairwise cosine-similarity matrix
between the two local ids' stored embeddings (already L2-normalized, so the dot
product is the cosine). Appearance never *creates* a match without spatial
evidence — it only disambiguates pairs that already have votes.

Pure function — no DB, no state.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

VOTE_WEIGHT       = 0.7
APPEARANCE_WEIGHT = 0.3


def _appearance_score(emb_a: np.ndarray | None, emb_b: np.ndarray | None) -> float:
    """Median pairwise cosine similarity between two (N, D) embedding stacks."""
    if emb_a is None or emb_b is None or emb_a.size == 0 or emb_b.size == 0:
        return 0.0
    sim = emb_a @ emb_b.T
    return float(np.median(sim))


def resolve_ambiguous(
    ambiguous_pairs,
    embeddings: dict,
    *,
    reid_fallback_threshold: float,
    details: list | None = None,
) -> set:
    """Resolve ambiguous pairs via appearance.

    ambiguous_pairs: iterable of (local_a, local_b, vote_rate).
    embeddings: {local_id: np.ndarray of shape (n, dim), L2-normalized rows}.
    Returns a set of confirmed (local_a, local_b, vote_rate). At most one
    local_b is confirmed per local_a (the highest combined score, if it clears
    the threshold).

    If `details` is provided (dev trace, VD1), the per-`a` best candidate's
    cosine/final/threshold/matched are appended — captured, not recomputed.
    """
    groups: dict[object, list[tuple]] = defaultdict(list)
    for a, b, vr in ambiguous_pairs:
        groups[a].append((b, vr))

    confirmed: set = set()
    for a, candidates in groups.items():
        emb_a = embeddings.get(a)
        best = None  # (b, vote_rate, final_score, appearance)
        for b, vr in candidates:
            appearance = _appearance_score(emb_a, embeddings.get(b))
            final = vr * VOTE_WEIGHT + appearance * APPEARANCE_WEIGHT
            if best is None or final > best[2]:
                best = (b, vr, final, appearance)
        if best is None:
            continue
        matched = best[2] >= reid_fallback_threshold
        if matched:
            confirmed.add((a, best[0], best[1]))
        if details is not None:
            details.append({
                "local_a": a, "local_b": best[0], "cosine": best[3],
                "final_score": best[2], "threshold": reid_fallback_threshold,
                "matched": matched,
            })
    return confirmed
