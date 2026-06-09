"""Stage 2 — per-pair spatial voting.

For one overlapping camera pair, repeatedly match co-visible detections by floor
position (Hungarian assignment per timestamp), counting how often each
cross-camera (local_a, local_b) pair is assigned and how often that assignment
is within VOTE_DISTANCE_THRESHOLD_M. A second Hungarian pass over the resulting
vote-rate matrix picks one best counterpart per local id, classified as:

  * confirmed — vote_rate ≥ MIN_VOTE_RATE and votes ≥ MIN_VOTES
  * ambiguous — votes ≥ MIN_VOTES but vote_rate below the confirm bar, OR the
    top-two candidates for a local id are within AMBIGUITY_MARGIN of each other
    (these go to the appearance fallback, Stage 3)

Pure function — no DB, no state. Floor coordinates are metres.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from math import hypot

import numpy as np
from scipy.optimize import linear_sum_assignment

# Observations for one camera: {local_id: [(timestamp_ms, floor_x, floor_y), ...]}
Observations = dict


def _build_ts_index(observations: Observations) -> dict[int, list[tuple]]:
    """Invert to {timestamp_ms: [(local_id, x, y), ...]}."""
    index: dict[int, list[tuple]] = defaultdict(list)
    for local_id, dets in observations.items():
        for ts, x, y in dets:
            index[ts].append((local_id, x, y))
    return index


def _nearest_ts(sorted_ts: list[int], target: int, tol: int) -> int | None:
    """Nearest timestamp to `target` within `tol`, or None."""
    if not sorted_ts:
        return None
    i = bisect.bisect_left(sorted_ts, target)
    best, best_d = None, None
    for j in (i - 1, i):
        if 0 <= j < len(sorted_ts):
            d = abs(sorted_ts[j] - target)
            if d <= tol and (best_d is None or d < best_d):
                best, best_d = sorted_ts[j], d
    return best


def vote_camera_pair(
    obs_a: Observations,
    obs_b: Observations,
    *,
    vote_distance_threshold_m: float,
    min_vote_rate: float,
    min_votes: int,
    temporal_tolerance_ms: int,
    ambiguity_margin: float,
    details: list | None = None,
) -> tuple[set, set]:
    """Vote one camera pair.

    Returns (confirmed, ambiguous), each a set of (local_a, local_b, vote_rate).

    If `details` is provided (dev trace, VD1), the per-decision votes/co_visible
    already computed here are appended to it — never recomputed, off by default.
    """
    idx_a = _build_ts_index(obs_a)
    idx_b = _build_ts_index(obs_b)
    if not idx_a or not idx_b:
        return set(), set()

    sorted_b_ts = sorted(idx_b)

    votes: dict[tuple, int] = defaultdict(int)
    co_visible: dict[tuple, int] = defaultdict(int)

    for ts_a, dets_a in idx_a.items():
        ts_b = _nearest_ts(sorted_b_ts, ts_a, temporal_tolerance_ms)
        if ts_b is None:
            continue
        dets_b = idx_b[ts_b]
        if not dets_a or not dets_b:
            continue

        # Distance matrix (metres) → optimal 1:1 assignment for this instant.
        dist = np.array(
            [[hypot(ax - bx, ay - by) for _, bx, by in dets_b] for _, ax, ay in dets_a],
            dtype=np.float64,
        )
        row_ind, col_ind = linear_sum_assignment(dist)
        for i, j in zip(row_ind, col_ind):
            pair = (dets_a[i][0], dets_b[j][0])
            co_visible[pair] += 1
            if dist[i, j] <= vote_distance_threshold_m:
                votes[pair] += 1

    if not co_visible:
        return set(), set()

    vote_rate = {pair: votes[pair] / cv for pair, cv in co_visible.items() if cv >= 1}

    # Build the vote-rate matrix over co-visible local ids and pick one best
    # counterpart per local id (Hungarian on 1 - vote_rate).
    a_locals = sorted({a for a, _ in co_visible}, key=str)
    b_locals = sorted({b for _, b in co_visible}, key=str)
    score = np.array(
        [[vote_rate.get((a, b), 0.0) for b in b_locals] for a in a_locals],
        dtype=np.float64,
    )
    row_ind, col_ind = linear_sum_assignment(1.0 - score)

    confirmed: dict[tuple, float] = {}
    ambiguous: dict[tuple, float] = {}
    assigned_b: dict[object, object] = {}

    for i, j in zip(row_ind, col_ind):
        a, b = a_locals[i], b_locals[j]
        assigned_b[a] = b
        vr = vote_rate.get((a, b), 0.0)
        v = votes.get((a, b), 0)
        if vr >= min_vote_rate and v >= min_votes:
            confirmed[(a, b)] = vr
        elif vr > 0.0 and v >= min_votes:
            ambiguous[(a, b)] = vr

    # Ambiguity margin: if a local id's top-two candidates are within the margin,
    # its assigned pair is ambiguous regardless of absolute vote_rate — demote
    # from confirmed so the appearance fallback decides.
    for idx_i, a in enumerate(a_locals):
        rates = sorted((score[idx_i]).tolist(), reverse=True)
        if len(rates) >= 2 and rates[0] > 0.0 and (rates[0] - rates[1]) < ambiguity_margin:
            b = assigned_b.get(a)
            if b is None:
                continue
            vr = vote_rate.get((a, b), 0.0)
            if vr <= 0.0:
                continue
            confirmed.pop((a, b), None)
            ambiguous[(a, b)] = vr

    if details is not None:
        for klass, decisions in (("confirmed", confirmed), ("ambiguous", ambiguous)):
            for (a, b), vr in decisions.items():
                details.append({
                    "local_a": a, "local_b": b, "vote_rate": vr,
                    "votes": votes.get((a, b), 0), "co_visible": co_visible.get((a, b), 0),
                    "class": klass,
                })

    confirmed_set = {(a, b, vr) for (a, b), vr in confirmed.items()}
    ambiguous_set = {(a, b, vr) for (a, b), vr in ambiguous.items()}
    return confirmed_set, ambiguous_set
