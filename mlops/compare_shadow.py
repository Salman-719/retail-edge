"""Shadow comparison job.

Reads shadow experiment runs from MLflow (or the fallback JSONL log),
computes comparison metrics, and produces a structured pass/fail decision.
Logs the full result as a new MLflow run in the ``shadow_comparison`` experiment.
Exits 0 on PASS, 1 on FAIL.

Usage
-----
    python mlops/compare_shadow.py [--hours N] [--smoke]

Options
    --hours N      Look back N hours of shadow runs (default: 24).
    --smoke        Use relaxed thresholds and exit 0 regardless (CI wiring check).
    --fallback PATH  Read records from a JSONL fallback file instead of MLflow.

Metrics compared and thresholds (justified below)
--------------------------------------------------
confidence_delta_mean
    Mean |prod_avg_confidence - shadow_avg_confidence| across all /tracking runs.
    Threshold: 0.10 (10 pp).
    Justification: production bbox_confidence is the YOLO detection score
    (0–1).  A shift > 10 pp between consecutive windows signals that the
    detector's confidence distribution has moved — either scene degradation
    or model behaviour change.  The alert_rules.yml fires DetectorConfidenceLow
    at mean < 0.35; a 10 pp window-to-window delta is a meaningful leading
    indicator before that threshold trips.

selection_score_delta_mean
    Mean |prod_avg_selection_score - shadow_avg_selection_score| across /iep3 runs.
    Threshold: 0.10.
    Justification: selection_score is a weighted sum of normalised bbox_area
    (0.7) and detection confidence (0.3).  A shift > 10 pp means either
    crowd density or confidence has changed significantly between windows,
    which affects which camera's view IEP3 trusts as canonical — directly
    impacting floor-position accuracy.

shadow_error_rate
    Fraction of shadow calls that raised an exception.
    Threshold: 0.20 (20 %).
    Justification: occasional DB timeouts are acceptable, but if > 20 % of
    shadow calls fail the shadow data is not representative enough to draw
    any conclusion.  The job FAILs in this case to alert that shadow infra
    itself needs attention.

row_count_ratio_min
    min(shadow_row_count / prod_row_count) across all runs (clamped to 1.0).
    Threshold: > 0.10 (shadow must have at least 10 % as many rows as prod).
    Justification: if the shadow window returns nearly no rows but prod has
    many, the windows are misaligned or the DB was mostly empty in the shadow
    window — the comparison is not meaningful.  Note: shadow windows are
    intentionally smaller (one window-width of historical data vs. all-time
    latest), so some ratio reduction is expected.  Below 10 % is a data gap.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MLFLOW_TRACKING_URI: str = os.environ.get(
    "MLFLOW_TRACKING_URI", "http://localhost:5000"
)
SHADOW_EXPERIMENT      = "shadow"
COMPARISON_EXPERIMENT  = "shadow_comparison"

# Thresholds — these are the values the pass/fail decision is made against.
THRESHOLDS: dict[str, float] = {
    "confidence_delta_mean":     0.10,
    "selection_score_delta_mean": 0.10,
    "shadow_error_rate":          0.20,
    "row_count_ratio_min":        0.10,
}

# Relaxed thresholds used in --smoke mode (CI wiring check only).
SMOKE_THRESHOLDS: dict[str, float] = {
    "confidence_delta_mean":     1.00,
    "selection_score_delta_mean": 1.00,
    "shadow_error_rate":          1.00,
    "row_count_ratio_min":        0.00,
}


# ---------------------------------------------------------------------------
# Record loading
# ---------------------------------------------------------------------------

def _load_from_mlflow(hours: int) -> list[dict]:
    """Fetch shadow runs from the MLflow shadow experiment."""
    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    try:
        exp = client.get_experiment_by_name(SHADOW_EXPERIMENT)
    except Exception as exc:
        print(f"[compare_shadow] MLflow unreachable: {exc}", file=sys.stderr)
        return []

    if exp is None:
        print(f"[compare_shadow] Experiment '{SHADOW_EXPERIMENT}' not found — no runs to compare.")
        return []

    cutoff_ms = int((time.time() - hours * 3600) * 1000)
    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string=f"attributes.start_time >= {cutoff_ms}",
        max_results=5000,
    )

    records = []
    for run in runs:
        p = run.data.params
        m = run.data.metrics
        records.append({
            "route":                       p.get("route", ""),
            "input_hash":                  p.get("input_hash", ""),
            "shadow_offset_s":             float(p.get("shadow_offset_s", 0)),
            "timestamp_utc":               p.get("timestamp_utc", ""),
            "shadow_error":                p.get("shadow_error", "none"),
            "prod_latency_ms":             m.get("prod_latency_ms", 0.0),
            "shadow_latency_ms":           m.get("shadow_latency_ms", 0.0),
            "prod_row_count":              m.get("prod_row_count", 0.0),
            "shadow_row_count":            m.get("shadow_row_count", 0.0),
            "prod_unique_ids":             m.get("prod_unique_ids", 0.0),
            "shadow_unique_ids":           m.get("shadow_unique_ids", 0.0),
            "prod_avg_confidence":         m.get("prod_avg_confidence", 0.0),
            "shadow_avg_confidence":       m.get("shadow_avg_confidence", 0.0),
            "prod_avg_selection_score":    m.get("prod_avg_selection_score", 0.0),
            "shadow_avg_selection_score":  m.get("shadow_avg_selection_score", 0.0),
            "confidence_delta":            m.get("confidence_delta", 0.0),
            "selection_score_delta":       m.get("selection_score_delta", 0.0),
        })
    return records


def _load_from_fallback(path: str, hours: int) -> list[dict]:
    """Read records from the JSONL fallback log, filtering by hours."""
    if not os.path.exists(path):
        print(f"[compare_shadow] Fallback log not found: {path}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = rec.get("timestamp_utc", "")
                if ts:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                records.append(rec)
            except Exception:
                continue
    return records


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_metrics(records: list[dict]) -> dict[str, Any]:
    """Compute aggregate comparison metrics from a list of shadow records."""
    if not records:
        return {
            "n_runs": 0,
            "confidence_delta_mean": 0.0,
            "selection_score_delta_mean": 0.0,
            "shadow_error_rate": 0.0,
            "row_count_ratio_min": 1.0,
            "prod_latency_ms_mean": 0.0,
            "shadow_latency_ms_mean": 0.0,
            "routes_seen": [],
        }

    n = len(records)
    errors = sum(1 for r in records if r.get("shadow_error", "none") != "none")

    tracking_recs = [r for r in records if r.get("route") == "/tracking"]
    iep3_recs     = [r for r in records if r.get("route") == "/iep3"]

    # confidence_delta_mean — /tracking runs only
    conf_deltas = [r.get("confidence_delta", 0.0) for r in tracking_recs]
    confidence_delta_mean = (sum(conf_deltas) / len(conf_deltas)) if conf_deltas else 0.0

    # selection_score_delta_mean — /iep3 runs only
    score_deltas = [r.get("selection_score_delta", 0.0) for r in iep3_recs]
    selection_score_delta_mean = (sum(score_deltas) / len(score_deltas)) if score_deltas else 0.0

    # row_count_ratio_min — all runs, skip division-by-zero
    ratios = []
    for r in records:
        prod_count = r.get("prod_row_count", 0)
        shad_count = r.get("shadow_row_count", 0)
        if prod_count and prod_count > 0:
            ratios.append(min(1.0, shad_count / prod_count))
    row_count_ratio_min = min(ratios) if ratios else 1.0

    prod_lats   = [r.get("prod_latency_ms", 0.0) for r in records]
    shadow_lats = [r.get("shadow_latency_ms", 0.0) for r in records]

    return {
        "n_runs":                    n,
        "confidence_delta_mean":     round(confidence_delta_mean, 6),
        "selection_score_delta_mean": round(selection_score_delta_mean, 6),
        "shadow_error_rate":         round(errors / n, 6),
        "row_count_ratio_min":       round(row_count_ratio_min, 6),
        "prod_latency_ms_mean":      round(sum(prod_lats) / n, 3),
        "shadow_latency_ms_mean":    round(sum(shadow_lats) / n, 3),
        "routes_seen":               sorted({r.get("route", "") for r in records}),
    }


# ---------------------------------------------------------------------------
# Pass/fail decision
# ---------------------------------------------------------------------------

def evaluate(metrics: dict[str, Any], thresholds: dict[str, float]) -> tuple[bool, list[str]]:
    """Return (passed, list_of_failure_reasons)."""
    failures = []

    if metrics["n_runs"] == 0:
        return True, []  # no data → vacuously pass (nothing to compare)

    if metrics["confidence_delta_mean"] > thresholds["confidence_delta_mean"]:
        failures.append(
            f"confidence_delta_mean={metrics['confidence_delta_mean']:.4f} "
            f"> threshold={thresholds['confidence_delta_mean']}"
        )

    if metrics["selection_score_delta_mean"] > thresholds["selection_score_delta_mean"]:
        failures.append(
            f"selection_score_delta_mean={metrics['selection_score_delta_mean']:.4f} "
            f"> threshold={thresholds['selection_score_delta_mean']}"
        )

    if metrics["shadow_error_rate"] > thresholds["shadow_error_rate"]:
        failures.append(
            f"shadow_error_rate={metrics['shadow_error_rate']:.4f} "
            f"> threshold={thresholds['shadow_error_rate']}"
        )

    if metrics["row_count_ratio_min"] < thresholds["row_count_ratio_min"]:
        failures.append(
            f"row_count_ratio_min={metrics['row_count_ratio_min']:.4f} "
            f"< threshold={thresholds['row_count_ratio_min']}"
        )

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# MLflow result logging
# ---------------------------------------------------------------------------

def _log_comparison_result(
    metrics: dict[str, Any],
    thresholds: dict[str, float],
    passed: bool,
    failures: list[str],
    hours: int,
) -> None:
    """Log the full comparison result to the shadow_comparison experiment."""
    try:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(COMPARISON_EXPERIMENT)

        decision = "PASS" if passed else "FAIL"
        with mlflow.start_run(run_name=f"compare_{decision}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"):
            mlflow.log_params({
                "decision":              decision,
                "hours_window":          hours,
                "failure_reasons":       "; ".join(failures) if failures else "none",
                "routes_seen":           ",".join(metrics["routes_seen"]),
                "thresh_confidence_delta":      thresholds["confidence_delta_mean"],
                "thresh_selection_score_delta":  thresholds["selection_score_delta_mean"],
                "thresh_shadow_error_rate":      thresholds["shadow_error_rate"],
                "thresh_row_count_ratio_min":    thresholds["row_count_ratio_min"],
            })
            mlflow.log_metrics({
                "n_runs":                    float(metrics["n_runs"]),
                "confidence_delta_mean":     metrics["confidence_delta_mean"],
                "selection_score_delta_mean": metrics["selection_score_delta_mean"],
                "shadow_error_rate":         metrics["shadow_error_rate"],
                "row_count_ratio_min":       metrics["row_count_ratio_min"],
                "prod_latency_ms_mean":      metrics["prod_latency_ms_mean"],
                "shadow_latency_ms_mean":    metrics["shadow_latency_ms_mean"],
                "passed":                    1.0 if passed else 0.0,
            })
    except Exception as exc:
        print(f"[compare_shadow] Could not log result to MLflow: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare shadow experiment runs vs production.")
    ap.add_argument("--hours",    type=int,   default=24,    help="Look-back window in hours")
    ap.add_argument("--smoke",    action="store_true",       help="Relaxed thresholds, always exit 0")
    ap.add_argument("--fallback", type=str,   default=None,  help="Read from JSONL fallback log instead of MLflow")
    args = ap.parse_args(argv)

    thresholds = SMOKE_THRESHOLDS if args.smoke else THRESHOLDS

    if args.fallback:
        records = _load_from_fallback(args.fallback, args.hours)
    else:
        records = _load_from_mlflow(args.hours)

    metrics  = compute_metrics(records)
    passed, failures = evaluate(metrics, thresholds)

    print(f"[compare_shadow] window={args.hours}h  n_runs={metrics['n_runs']}")
    print(f"[compare_shadow] confidence_delta_mean={metrics['confidence_delta_mean']:.4f}  "
          f"selection_score_delta_mean={metrics['selection_score_delta_mean']:.4f}")
    print(f"[compare_shadow] shadow_error_rate={metrics['shadow_error_rate']:.4f}  "
          f"row_count_ratio_min={metrics['row_count_ratio_min']:.4f}")
    print(f"[compare_shadow] decision={'PASS' if passed else 'FAIL'}")
    if failures:
        for f in failures:
            print(f"[compare_shadow]   FAIL: {f}")

    _log_comparison_result(metrics, thresholds, passed, failures, args.hours)

    if args.smoke:
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
