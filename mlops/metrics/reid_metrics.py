"""ReID metrics — pure functions + a ReidStats -> metric-dict converter.

IMPORTANT — no per-person identity ground truth exists for the clips (we have
total_people=16, not "who is who when"). So the TRUE ReID-quality metrics
(false-merge rate, validated match accuracy) CANNOT be computed honestly. This
experiment uses PROXY metrics only, computed from the recovery logic's behavior:

  unique_local_ids        : distinct identities the lost-pool recovery ends with
  count_error             : |unique_local_ids - total_people| (proxy: ideal = 0)
  reid_attempts           : # of times recovery was attempted (new track checked lost pool)
  reid_recoveries         : # of times a lost track was re-matched to a prior identity
  reid_match_rate         : reid_recoveries / reid_attempts  (NOT validated as correct)
  new_id_rate             : 1 - match_rate (how often recovery FAILED -> minted a new id)
  avg_recovery_similarity : mean cosine of accepted recoveries (embedding confidence)
  embedding_dim / avg_embed_ms / total_runtime_s : time/space cost

`reid_false_merge_rate` is kept as a helper but NOT logged: it requires identity
labels to know a merge was *wrong*. `id_switches` was dropped (duplicated
reid_recoveries in this harness). GPU/CPU/mem are auto-logged as MLflow system
metrics (pynvml installed for gpu_utilization + gpu_memory).
"""
from __future__ import annotations


def count_error(unique_local_ids: int, total_people_gt: int) -> int:
    """Proxy: distinct local_ids vs ground-truth total people. 0 = the recovery
    produced exactly the right identity count (no over-splitting, no over-merging).
    NOTE: like detection, this is a count proxy — it does not verify the identities
    are the *right* people, only that the *number* matches."""
    return abs(unique_local_ids - total_people_gt)


def reid_match_rate(reid_recoveries: int, reid_attempts: int) -> float:
    """Proxy: fraction of recovery attempts that re-matched a lost identity.
    Higher = the embedding is discriminative enough to recognise returning people.
    NOT validated against ground truth — a high rate could include wrong merges."""
    return reid_recoveries / reid_attempts if reid_attempts else 0.0


def reid_false_merge_rate(wrong_merges: int, total_recoveries: int) -> float:
    """Requires identity ground truth to know a merge was wrong — NOT computable on
    these clips, so NOT logged. Kept for the future labelled-clip path."""
    return wrong_merges / total_recoveries if total_recoveries else 0.0


def programmable_metrics(stats, total_people_gt: int) -> dict:
    """Convert raw ReidStats (from the reid harness) into the proxy metric dict.

    Dropped `id_switches` — in this harness it equalled `reid_recoveries` exactly
    (a duplicate). Added new_id_rate, avg_recovery_similarity, total_runtime_s.
    """
    unique = stats.unique_local_ids
    attempts = stats.reid_attempts
    return {
        # ── identity / quality proxies (no ground-truth identity) ──────────────
        "unique_local_ids":        unique,
        "count_error":             count_error(unique, total_people_gt),
        "reid_attempts":           attempts,
        "reid_recoveries":         stats.reid_recoveries,
        "reid_match_rate":         reid_match_rate(stats.reid_recoveries, attempts),
        # how often recovery FAILED (minted a new id instead) — inverse view
        "new_id_rate":             (1.0 - stats.reid_recoveries / attempts) if attempts else 0.0,
        # mean cosine of accepted recoveries — how confident the embedding is
        "avg_recovery_similarity": (stats.sum_recovery_sim / stats.reid_recoveries
                                    if stats.reid_recoveries else 0.0),
        # ── time / space ──────────────────────────────────────────────────────
        "embedding_dim":           stats.embedding_dim,        # 512 (OSNet) / 2048 (ResNet)
        "avg_embed_ms":            stats.avg_embed_ms,         # per-crop embed time
        "total_runtime_s":         stats.total_runtime_s,      # wall-clock per run
        "frames_processed":        stats.frames_processed,
    }
