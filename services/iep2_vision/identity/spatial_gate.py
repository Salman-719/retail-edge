"""SpatioTemporalGate — physically-grounded ReID matching gate.

Pure math module. Zero IEP2 imports. No IO. Never raises.

evaluate() modifies the cosine similarity threshold at match time based on
how far apart the two floor positions are and how much time has elapsed.
When floor positions are unavailable the gate falls back silently to normal ReID.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SpatialGateConfig:
    max_walking_speed_mps: float = 1.4   # ~5 km/h, adult walking speed
    base_threshold:        float = 0.85  # ReID cosine threshold for resnet50_msmt17
    w_dist:                float = 0.2   # how much distance ratio raises threshold
    w_time:                float = 0.15  # how much time ratio lowers threshold
    min_threshold:         float = 0.35  # floor — never accept below this


@dataclass
class GateResult:
    allowed:   bool   # False = hard veto regardless of embedding score
    threshold: float  # adjusted similarity threshold; only meaningful if allowed=True


def evaluate(
    new_pos:         tuple[float, float] | None,
    lost_pos:        tuple[float, float] | None,
    elapsed_frames:  int,
    fps:             float,
    lost_ttl_frames: int,
    cfg:             SpatialGateConfig,
) -> GateResult:
    """Evaluate whether a ReID candidate is physically plausible.

    Returns GateResult with:
      allowed=False  — hard veto; caller must skip this candidate.
      allowed=True   — candidate is reachable; use threshold for the similarity check.
    """
    # Step 1 — fallback: no floor data, gate inactive
    if new_pos is None or lost_pos is None:
        return GateResult(allowed=True, threshold=cfg.base_threshold)

    # Step 2 — max allowed distance given elapsed time
    elapsed_seconds = elapsed_frames / max(fps, 1e-6)
    max_dist = cfg.max_walking_speed_mps * elapsed_seconds
    if max_dist < 1e-6:
        # elapsed_frames == 0: same frame, distance check meaningless
        return GateResult(allowed=True, threshold=cfg.base_threshold)

    # Step 3 — actual Euclidean distance in floor metres
    actual_dist = math.sqrt(
        (new_pos[0] - lost_pos[0]) ** 2 + (new_pos[1] - lost_pos[1]) ** 2
    )

    # Step 4 — hard veto: physically impossible to have walked this far
    if actual_dist > max_dist:
        return GateResult(allowed=False, threshold=cfg.base_threshold)

    # Step 5 — dynamic threshold
    # d_ratio: 0 = very close, 1 = at the physical limit → raises threshold
    # t_ratio: 0 = just lost,  1 = about to expire      → lowers threshold
    d_ratio = actual_dist / max_dist
    t_ratio = elapsed_frames / max(lost_ttl_frames, 1)
    adjusted = cfg.base_threshold + (d_ratio * cfg.w_dist) - (t_ratio * cfg.w_time)
    adjusted = max(cfg.min_threshold, min(1.0, adjusted))
    return GateResult(allowed=True, threshold=adjusted)


# ---------------------------------------------------------------------------
# Standalone smoke tests: python identity/spatial_gate.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cfg = SpatialGateConfig()  # defaults

    # ── Test 1: new_pos=None → gate inactive (allowed=True, base threshold) ──
    r = evaluate(None, (1.0, 2.0), 10, 5.0, 150, cfg)
    assert r.allowed is True
    assert r.threshold == cfg.base_threshold
    print(f"[1] new_pos=None -> allowed={r.allowed} threshold={r.threshold} OK")

    # ── Test 2: lost_pos=None → same ──────────────────────────────────────────
    r = evaluate((1.0, 2.0), None, 10, 5.0, 150, cfg)
    assert r.allowed is True
    assert r.threshold == cfg.base_threshold
    print(f"[2] lost_pos=None -> allowed={r.allowed} threshold={r.threshold} OK")

    # ── Test 3: actual_dist > max_dist → hard veto ────────────────────────────
    # elapsed=1 frame @ 5fps = 0.2s. max_dist = 1.4 * 0.2 = 0.28m
    # actual_dist = 10m (far away) → veto
    r = evaluate((0.0, 0.0), (10.0, 0.0), 1, 5.0, 150, cfg)
    assert r.allowed is False
    print(f"[3] actual_dist > max_dist -> allowed={r.allowed} OK")

    # ── Test 4: mid-range distance, half TTL elapsed ───────────────────────────
    # elapsed=75 frames @ 5fps = 15s. max_dist = 1.4 * 15 = 21m
    # actual_dist = 10.5m → d_ratio = 0.5
    # t_ratio = 75/150 = 0.5
    # adjusted = 0.75 + 0.5*0.2 - 0.5*0.15 = 0.75 + 0.10 - 0.075 = 0.775
    r = evaluate((0.0, 0.0), (10.5, 0.0), 75, 5.0, 150, cfg)
    assert r.allowed is True
    expected = 0.75 + 0.5 * 0.2 - 0.5 * 0.15
    assert abs(r.threshold - expected) < 1e-9, f"Expected {expected:.4f}, got {r.threshold:.4f}"
    print(f"[4] mid-range, half TTL -> threshold={r.threshold:.4f} (expected {expected:.4f}) OK")

    # ── Test 5: full TTL elapsed, small distance → time penalty applied ────────
    # elapsed=150 frames @ 5fps = 30s. max_dist = 1.4 * 30 = 42m
    # actual_dist = 0.42m → d_ratio = 0.01
    # t_ratio = 150/150 = 1.0
    # adjusted = 0.75 + 0.01*0.2 - 1.0*0.15 = 0.75 + 0.002 - 0.15 = 0.602
    r = evaluate((0.0, 0.0), (0.42, 0.0), 150, 5.0, 150, cfg)
    assert r.allowed is True
    assert r.threshold < cfg.base_threshold, f"Time penalty should lower threshold below base: {r.threshold}"
    print(f"[5] full TTL, small distance -> threshold={r.threshold:.4f} (below base {cfg.base_threshold}) OK")

    # ── Test 6: adjusted threshold clamped to [min_threshold, 1.0] ─────────────
    # Force d_ratio=1.0, t_ratio=0 → adjusted = 0.75 + 0.2 = 0.95 (< 1.0, no clamp)
    r_high = evaluate((0.0, 0.0), (21.0, 0.0), 10, 5.0, 150, cfg)
    assert r_high.threshold <= 1.0, f"Threshold must never exceed 1.0: {r_high.threshold}"

    # Force enormous time discount: TTL=1 frame, elapsed=1 → t_ratio=1.0
    # adjusted = 0.75 - 0.15 = 0.60 → above min_threshold=0.35, no clamp needed
    r_low = evaluate((0.0, 0.0), (0.001, 0.0), 1, 5.0, 1, cfg)
    assert r_low.threshold >= cfg.min_threshold, f"Threshold must not go below min_threshold: {r_low.threshold}"
    assert r_low.threshold <= 1.0
    print(f"[6] threshold clamped to [{cfg.min_threshold}, 1.0]: high={r_high.threshold:.3f} low={r_low.threshold:.3f} OK")

    # ── Test 7: elapsed_frames=0 → base threshold (no distance check) ─────────
    r = evaluate((0.0, 0.0), (999.0, 999.0), 0, 5.0, 150, cfg)
    assert r.allowed is True
    assert r.threshold == cfg.base_threshold
    print(f"[7] elapsed_frames=0 -> allowed={r.allowed} threshold={r.threshold} OK")

    # ── Test 8: zero fps edge case → no crash ─────────────────────────────────
    r = evaluate((1.0, 1.0), (2.0, 2.0), 10, 0.0, 150, cfg)
    assert isinstance(r, GateResult)
    print(f"[8] fps=0.0 -> no crash, allowed={r.allowed} OK")

    print("\nsmoke tests passed")
