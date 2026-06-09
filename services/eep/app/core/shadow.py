"""Shadow fan-out and logging for the EEP dev-pipeline read routes.

Design contract
---------------
* Production response is returned to the caller BEFORE this module does
  anything observable.  The caller fires asyncio.create_task(_shadow_call(...))
  after building the production result; the task is fire-and-forget.
* Any exception inside a shadow task — query failure, MLflow unreachable,
  disk full — is caught, logged at WARNING level, and silently discarded.
  It NEVER propagates to the caller.
* MLflow logging uses a synchronous mlflow client run in a thread executor so
  it does not block the asyncio event loop.
* If MLflow is unreachable the record is appended to SHADOW_FALLBACK_LOG
  (a .jsonl file) atomically via append mode.  If that also fails the failure
  is logged and discarded — shadow logging cannot crash the EEP.

Logged per shadow call (both MLflow params/metrics and fallback JSON):
  params : route, input_hash, shadow_offset_s, timestamp_utc, shadow_error
  metrics: prod_latency_ms, shadow_latency_ms, prod_row_count,
           shadow_row_count, prod_unique_ids, shadow_unique_ids,
           prod_avg_confidence, shadow_avg_confidence,
           prod_avg_selection_score, shadow_avg_selection_score,
           confidence_delta, selection_score_delta
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MLFLOW_TRACKING_URI: str = os.environ.get(
    "MLFLOW_TRACKING_URI", "http://mlflow:5000"
)
SHADOW_EXPERIMENT: str = "shadow"

# Fallback local log written when MLflow is unreachable.
SHADOW_FALLBACK_LOG: str = os.environ.get(
    "SHADOW_FALLBACK_LOG",
    os.path.join(os.path.dirname(__file__), "../../../../shadow_fallback.jsonl"),
)

# How far back (seconds) to shift the shadow query relative to the production
# query's most-recent timestamp.  Default = one full pipeline window (60 s).
SHADOW_OFFSET_S: float = float(os.environ.get("SHADOW_OFFSET_S", "60"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _input_hash(*parts: Any) -> str:
    """Stable SHA-256 hex digest of the stringified query parameters."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _stats_tracking(rows: list[dict]) -> dict:
    """Derive aggregate stats from tracking_history rows."""
    confs = [r.get("bbox_confidence") for r in rows if r.get("bbox_confidence") is not None]
    unique_ids = len({r.get("local_id") for r in rows if r.get("local_id")})
    return {
        "row_count": len(rows),
        "unique_ids": unique_ids,
        "avg_confidence": (sum(confs) / len(confs)) if confs else 0.0,
        "avg_selection_score": 0.0,
    }


def _stats_iep3(rows: list[dict]) -> dict:
    """Derive aggregate stats from global_tracking_history rows."""
    scores = [r.get("selection_score") for r in rows if r.get("selection_score") is not None]
    unique_ids = len({r.get("global_id") for r in rows if r.get("global_id")})
    return {
        "row_count": len(rows),
        "unique_ids": unique_ids,
        "avg_confidence": 0.0,
        "avg_selection_score": (sum(scores) / len(scores)) if scores else 0.0,
    }


def _log_to_mlflow(record: dict) -> None:
    """Synchronous MLflow log — called from a thread executor."""
    import mlflow  # imported lazily: not in base EEP requirements in prod

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(SHADOW_EXPERIMENT)
    with mlflow.start_run(run_name=record["route"] + "_" + record["input_hash"]):
        mlflow.log_params({
            "route":            record["route"],
            "input_hash":       record["input_hash"],
            "shadow_offset_s":  record["shadow_offset_s"],
            "timestamp_utc":    record["timestamp_utc"],
            "shadow_error":     record.get("shadow_error", "none"),
        })
        mlflow.log_metrics({
            "prod_latency_ms":          record["prod_latency_ms"],
            "shadow_latency_ms":        record["shadow_latency_ms"],
            "prod_row_count":           record["prod_row_count"],
            "shadow_row_count":         record["shadow_row_count"],
            "prod_unique_ids":          record["prod_unique_ids"],
            "shadow_unique_ids":        record["shadow_unique_ids"],
            "prod_avg_confidence":      record["prod_avg_confidence"],
            "shadow_avg_confidence":    record["shadow_avg_confidence"],
            "prod_avg_selection_score": record["prod_avg_selection_score"],
            "shadow_avg_selection_score": record["shadow_avg_selection_score"],
            "confidence_delta":         record["confidence_delta"],
            "selection_score_delta":    record["selection_score_delta"],
        })


def _log_to_fallback(record: dict) -> None:
    """Append one JSON line to the local fallback log."""
    path = os.path.abspath(SHADOW_FALLBACK_LOG)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _persist_record(record: dict) -> None:
    """Try MLflow; fall back to local file; swallow all failures."""
    try:
        _log_to_mlflow(record)
        return
    except Exception as exc:
        log.warning("shadow: MLflow unreachable (%s), writing to fallback log", exc)

    try:
        _log_to_fallback(record)
    except Exception as exc:
        log.warning("shadow: fallback log write failed (%s) — record discarded", exc)


# ---------------------------------------------------------------------------
# Public API: fire-and-forget shadow tasks
# ---------------------------------------------------------------------------

async def shadow_tracking(
    *,
    camera_id: str,
    limit: int,
    prod_rows: list[dict],
    prod_latency_ms: float,
    db_factory,          # callable() -> async context manager yielding AsyncSession
) -> None:
    """Run a shadow query for GET /tracking and log the comparison.

    The shadow query shifts the WHERE clause back by SHADOW_OFFSET_S seconds
    (converted to milliseconds from the minimum timestamp_ms in prod_rows so
    the offset is anchored to actual data, not wall-clock).
    """
    ihash = _input_hash(camera_id, limit)
    ts_utc = datetime.now(timezone.utc).isoformat()
    shadow_error = "none"
    shadow_rows: list[dict] = []
    shadow_latency_ms = 0.0

    try:
        from sqlalchemy import text as sa_text

        # Anchor: earliest timestamp in the production result.
        if prod_rows:
            anchor_ms = min(r.get("timestamp_ms", 0) for r in prod_rows)
        else:
            anchor_ms = int(time.time() * 1000)

        shadow_max_ms = anchor_ms
        shadow_min_ms = anchor_ms - int(SHADOW_OFFSET_S * 1000)

        t0 = time.monotonic()
        async with db_factory() as db:
            raw = (await db.execute(
                sa_text("""
                    WITH ranked AS (
                        SELECT local_id::text AS local_id, timestamp_ms,
                               floor_x, floor_y, zone_id::text AS zone_id,
                               bbox_confidence, bbox_area,
                               MIN(timestamp_ms) OVER (PARTITION BY local_id) AS id_first_seen,
                               ROW_NUMBER() OVER (PARTITION BY local_id ORDER BY timestamp_ms DESC) AS rn
                        FROM tracking_history
                        WHERE camera_id = :cam
                          AND timestamp_ms >= :tmin
                          AND timestamp_ms <  :tmax
                    )
                    SELECT local_id, timestamp_ms, floor_x, floor_y, zone_id,
                           bbox_confidence, bbox_area
                    FROM ranked
                    WHERE rn <= :lim
                    ORDER BY id_first_seen ASC, timestamp_ms DESC
                """),
                {"cam": camera_id, "tmin": shadow_min_ms, "tmax": shadow_max_ms, "lim": limit},
            )).mappings().all()
        shadow_latency_ms = (time.monotonic() - t0) * 1000
        shadow_rows = [dict(r) for r in raw]
    except Exception as exc:
        shadow_error = type(exc).__name__
        log.warning("shadow: tracking query failed for camera=%s: %s", camera_id, exc)

    prod_stats   = _stats_tracking(prod_rows)
    shadow_stats = _stats_tracking(shadow_rows)

    record = {
        "route":                    "/tracking",
        "input_hash":               ihash,
        "shadow_offset_s":          SHADOW_OFFSET_S,
        "timestamp_utc":            ts_utc,
        "shadow_error":             shadow_error,
        "prod_latency_ms":          round(prod_latency_ms, 3),
        "shadow_latency_ms":        round(shadow_latency_ms, 3),
        "prod_row_count":           prod_stats["row_count"],
        "shadow_row_count":         shadow_stats["row_count"],
        "prod_unique_ids":          prod_stats["unique_ids"],
        "shadow_unique_ids":        shadow_stats["unique_ids"],
        "prod_avg_confidence":      round(prod_stats["avg_confidence"], 6),
        "shadow_avg_confidence":    round(shadow_stats["avg_confidence"], 6),
        "prod_avg_selection_score": 0.0,
        "shadow_avg_selection_score": 0.0,
        "confidence_delta":         round(abs(prod_stats["avg_confidence"] - shadow_stats["avg_confidence"]), 6),
        "selection_score_delta":    0.0,
    }

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _persist_record, record)


async def shadow_iep3(
    *,
    store_id: str,
    limit: int,
    prod_rows: list[dict],
    prod_latency_ms: float,
    db_factory,
) -> None:
    """Run a shadow query for GET /iep3 and log the comparison."""
    ihash = _input_hash(store_id, limit)
    ts_utc = datetime.now(timezone.utc).isoformat()
    shadow_error = "none"
    shadow_rows: list[dict] = []
    shadow_latency_ms = 0.0

    try:
        from sqlalchemy import text as sa_text

        if prod_rows:
            anchor_ms = min(r.get("timestamp_ms", 0) for r in prod_rows)
        else:
            anchor_ms = int(time.time() * 1000)

        shadow_max_ms = anchor_ms
        shadow_min_ms = anchor_ms - int(SHADOW_OFFSET_S * 1000)

        t0 = time.monotonic()
        async with db_factory() as db:
            raw = (await db.execute(
                sa_text("""
                    SELECT global_id::text AS global_id, batch_number, timestamp_ms,
                           floor_x, floor_y, zone_id::text AS zone_id,
                           source_camera, selection_score
                    FROM global_tracking_history
                    WHERE store_id   = :store
                      AND timestamp_ms >= :tmin
                      AND timestamp_ms <  :tmax
                    ORDER BY timestamp_ms DESC
                    LIMIT :lim
                """),
                {"store": store_id, "tmin": shadow_min_ms, "tmax": shadow_max_ms, "lim": limit},
            )).mappings().all()
        shadow_latency_ms = (time.monotonic() - t0) * 1000
        shadow_rows = [dict(r) for r in raw]
    except Exception as exc:
        shadow_error = type(exc).__name__
        log.warning("shadow: iep3 query failed for store=%s: %s", store_id, exc)

    prod_stats   = _stats_iep3(prod_rows)
    shadow_stats = _stats_iep3(shadow_rows)

    record = {
        "route":                    "/iep3",
        "input_hash":               ihash,
        "shadow_offset_s":          SHADOW_OFFSET_S,
        "timestamp_utc":            ts_utc,
        "shadow_error":             shadow_error,
        "prod_latency_ms":          round(prod_latency_ms, 3),
        "shadow_latency_ms":        round(shadow_latency_ms, 3),
        "prod_row_count":           prod_stats["row_count"],
        "shadow_row_count":         shadow_stats["row_count"],
        "prod_unique_ids":          prod_stats["unique_ids"],
        "shadow_unique_ids":        shadow_stats["unique_ids"],
        "prod_avg_confidence":      0.0,
        "shadow_avg_confidence":    0.0,
        "prod_avg_selection_score": round(prod_stats["avg_selection_score"], 6),
        "shadow_avg_selection_score": round(shadow_stats["avg_selection_score"], 6),
        "confidence_delta":         0.0,
        "selection_score_delta":    round(abs(prod_stats["avg_selection_score"] - shadow_stats["avg_selection_score"]), 6),
    }

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _persist_record, record)
