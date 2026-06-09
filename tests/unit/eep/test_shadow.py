"""Unit tests for the EEP shadow fan-out and comparison job.

Coverage:
  A — Shadow failure does NOT affect the production response (isolation).
  B — Shadow result is logged correctly (both MLflow path and fallback path).
  C — Shadow comparison job produces correct pass/fail given mocked inputs.

All tests are pure unit tests: no running database, no MLflow server, no
asyncio event loop from an external source. Async tests use pytest-asyncio.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# The conftest.py has already added the EEP service root and mlops to sys.path.
import app.core.shadow as shadow_mod
import compare_shadow as cs


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_tracking_rows(n: int = 5, confidence: float = 0.85) -> list[dict]:
    return [
        {
            "local_id": f"lid-{i}",
            "timestamp_ms": 1_700_000_000_000 + i * 1000,
            "floor_x": float(i),
            "floor_y": float(i),
            "zone_id": None,
            "bbox_confidence": confidence,
            "bbox_area": 100_000.0,
        }
        for i in range(n)
    ]


def _make_iep3_rows(n: int = 3, score: float = 0.72) -> list[dict]:
    return [
        {
            "global_id": f"gid-{i}",
            "batch_number": i,
            "timestamp_ms": 1_700_000_000_000 + i * 60_000,
            "floor_x": float(i),
            "floor_y": float(i),
            "zone_id": None,
            "source_camera": f"cam-{i % 2}",
            "selection_score": score,
        }
        for i in range(n)
    ]


@asynccontextmanager
async def _fake_db_ok(rows: list[dict]):
    """Async context manager that yields a fake AsyncSession returning rows."""
    mappings_result = MagicMock()
    mappings_result.all.return_value = [MagicMock(**{"__iter__": lambda s: iter(r.items()), **r}) for r in rows]

    # Make mappings().all() return plain dicts
    execute_result = MagicMock()
    execute_result.mappings.return_value = mappings_result

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)
    yield db


@asynccontextmanager
async def _fake_db_error():
    """Fake DB session that raises on execute."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("DB down"))
    yield db


def _db_factory_ok(rows):
    """Return a zero-arg callable that produces _fake_db_ok(rows)."""
    def factory():
        return _fake_db_ok(rows)
    return factory


def _db_factory_error():
    def factory():
        return _fake_db_error()
    return factory


# ══════════════════════════════════════════════════════════════════════════════
# Group A — Isolation: shadow failure must not surface to the caller
# ══════════════════════════════════════════════════════════════════════════════

class TestShadowIsolation:
    """The production result is returned before the shadow task runs.
    Even when the shadow task raises, the caller sees the original value."""

    @pytest.mark.asyncio
    async def test_shadow_tracking_failure_does_not_raise(self):
        """shadow_tracking with a broken DB must silently swallow the error."""
        persisted = []

        with patch.object(shadow_mod, "_persist_record", side_effect=lambda r: persisted.append(r)):
            # DB factory raises on execute
            await shadow_mod.shadow_tracking(
                camera_id="cam-01",
                limit=50,
                prod_rows=_make_tracking_rows(5),
                prod_latency_ms=12.3,
                db_factory=_db_factory_error(),
            )

        # Must have logged exactly one record, with the error type captured.
        assert len(persisted) == 1
        assert persisted[0]["shadow_error"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_shadow_iep3_failure_does_not_raise(self):
        """shadow_iep3 with a broken DB must silently swallow the error."""
        persisted = []

        with patch.object(shadow_mod, "_persist_record", side_effect=lambda r: persisted.append(r)):
            await shadow_mod.shadow_iep3(
                store_id="store-abc",
                limit=50,
                prod_rows=_make_iep3_rows(3),
                prod_latency_ms=8.5,
                db_factory=_db_factory_error(),
            )

        assert len(persisted) == 1
        assert persisted[0]["shadow_error"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_persist_mlflow_failure_falls_back(self, tmp_path):
        """When MLflow raises, _persist_record must write to the fallback log."""
        fallback = str(tmp_path / "shadow_fallback.jsonl")
        record = {
            "route": "/tracking", "input_hash": "abc123",
            "shadow_offset_s": 60.0, "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "shadow_error": "none",
            "prod_latency_ms": 10.0, "shadow_latency_ms": 12.0,
            "prod_row_count": 5, "shadow_row_count": 4,
            "prod_unique_ids": 3, "shadow_unique_ids": 3,
            "prod_avg_confidence": 0.85, "shadow_avg_confidence": 0.83,
            "prod_avg_selection_score": 0.0, "shadow_avg_selection_score": 0.0,
            "confidence_delta": 0.02, "selection_score_delta": 0.0,
        }

        with patch.object(shadow_mod, "_log_to_mlflow", side_effect=ConnectionError("MLflow down")), \
             patch.object(shadow_mod, "SHADOW_FALLBACK_LOG", fallback):
            shadow_mod._persist_record(record)

        assert os.path.exists(fallback)
        lines = open(fallback).readlines()
        assert len(lines) == 1
        written = json.loads(lines[0])
        assert written["route"] == "/tracking"
        assert written["confidence_delta"] == 0.02

    @pytest.mark.asyncio
    async def test_persist_both_fail_does_not_raise(self, tmp_path):
        """When both MLflow and the fallback log fail, _persist_record swallows both."""
        record = {"route": "/tracking", "input_hash": "x"}
        with patch.object(shadow_mod, "_log_to_mlflow", side_effect=ConnectionError("MLflow down")), \
             patch.object(shadow_mod, "_log_to_fallback", side_effect=OSError("disk full")):
            # Must not raise
            shadow_mod._persist_record(record)

    @pytest.mark.asyncio
    async def test_shadow_task_does_not_block_production_return(self):
        """Demonstrate that create_task semantics don't block the caller.

        We simulate the route handler pattern: build the production result,
        fire the shadow task, return immediately. Even with a slow shadow
        coroutine the production response is available before the task runs.
        The key invariant: the handler returns BEFORE the shadow task body
        executes, so 'prod' is appended before 'shadow'.
        """
        order = []

        async def slow_shadow():
            await asyncio.sleep(0)  # yield once to event loop
            order.append("shadow")

        async def handler():
            order.append("prod")
            asyncio.create_task(slow_shadow())
            return "production_response"

        result = await handler()
        # Production response is returned immediately.
        assert result == "production_response"
        # 'prod' must already be in order; 'shadow' may or may not have run yet.
        assert "prod" in order
        assert order[0] == "prod"   # prod always comes first

        # Drain the event loop — shadow must complete after this.
        await asyncio.sleep(0.01)
        assert "shadow" in order
        assert order.index("prod") < order.index("shadow")


# ══════════════════════════════════════════════════════════════════════════════
# Group B — Logging: correct record structure written on success
# ══════════════════════════════════════════════════════════════════════════════

class TestShadowLogging:

    @pytest.mark.asyncio
    async def test_tracking_record_fields(self):
        """shadow_tracking must log all required fields with correct values."""
        prod_rows = _make_tracking_rows(5, confidence=0.80)
        # Shadow rows have lower confidence — delta should be non-zero.
        shadow_rows = _make_tracking_rows(4, confidence=0.70)
        persisted = []

        with patch.object(shadow_mod, "_persist_record", side_effect=lambda r: persisted.append(r)), \
             patch.object(shadow_mod, "SHADOW_OFFSET_S", 60.0):
            await shadow_mod.shadow_tracking(
                camera_id="cam-02",
                limit=50,
                prod_rows=prod_rows,
                prod_latency_ms=15.0,
                db_factory=_db_factory_ok(shadow_rows),
            )

        assert len(persisted) == 1
        rec = persisted[0]

        assert rec["route"] == "/tracking"
        assert rec["prod_row_count"] == 5
        assert rec["prod_unique_ids"] == 5          # 5 distinct local_ids
        assert abs(rec["prod_avg_confidence"] - 0.80) < 1e-4
        assert rec["shadow_error"] == "none"
        # Confidence delta must be positive (prod 0.80 vs shadow 0.70)
        assert rec["confidence_delta"] > 0.0
        assert "timestamp_utc" in rec
        assert "input_hash" in rec

    @pytest.mark.asyncio
    async def test_iep3_record_fields(self):
        """shadow_iep3 must log selection_score_delta, not confidence."""
        prod_rows = _make_iep3_rows(3, score=0.72)
        shadow_rows = _make_iep3_rows(2, score=0.60)
        persisted = []

        with patch.object(shadow_mod, "_persist_record", side_effect=lambda r: persisted.append(r)), \
             patch.object(shadow_mod, "SHADOW_OFFSET_S", 60.0):
            await shadow_mod.shadow_iep3(
                store_id="store-xyz",
                limit=50,
                prod_rows=prod_rows,
                prod_latency_ms=9.0,
                db_factory=_db_factory_ok(shadow_rows),
            )

        assert len(persisted) == 1
        rec = persisted[0]

        assert rec["route"] == "/iep3"
        assert rec["prod_row_count"] == 3
        assert rec["prod_unique_ids"] == 3
        assert abs(rec["prod_avg_selection_score"] - 0.72) < 1e-4
        assert rec["selection_score_delta"] > 0.0
        assert rec["confidence_delta"] == 0.0       # iep3 route never sets confidence

    @pytest.mark.asyncio
    async def test_input_hash_is_deterministic(self):
        """Same query params must produce the same input_hash."""
        h1 = shadow_mod._input_hash("cam-01", 50)
        h2 = shadow_mod._input_hash("cam-01", 50)
        h3 = shadow_mod._input_hash("cam-02", 50)
        assert h1 == h2
        assert h1 != h3

    @pytest.mark.asyncio
    async def test_fallback_log_append(self, tmp_path):
        """Multiple records written to fallback log must each appear on own line."""
        fallback = str(tmp_path / "shadow_fallback.jsonl")
        rec_a = {"route": "/tracking", "input_hash": "aaa"}
        rec_b = {"route": "/iep3",     "input_hash": "bbb"}

        with patch.object(shadow_mod, "SHADOW_FALLBACK_LOG", fallback):
            shadow_mod._log_to_fallback(rec_a)
            shadow_mod._log_to_fallback(rec_b)

        lines = open(fallback).readlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["input_hash"] == "aaa"
        assert json.loads(lines[1])["input_hash"] == "bbb"

    def test_stats_tracking_empty_rows(self):
        """_stats_tracking on empty list must return safe zeroes."""
        s = shadow_mod._stats_tracking([])
        assert s["row_count"] == 0
        assert s["avg_confidence"] == 0.0
        assert s["unique_ids"] == 0

    def test_stats_iep3_empty_rows(self):
        s = shadow_mod._stats_iep3([])
        assert s["row_count"] == 0
        assert s["avg_selection_score"] == 0.0
        assert s["unique_ids"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Group C — Comparison job: correct pass/fail from mocked records
# ══════════════════════════════════════════════════════════════════════════════

class TestComparisonJob:

    def _make_record(
        self, route="/tracking",
        confidence_delta=0.02, selection_score_delta=0.01,
        shadow_error="none",
        prod_row_count=10, shadow_row_count=9,
        prod_avg_confidence=0.85, shadow_avg_confidence=0.83,
        prod_avg_selection_score=0.70, shadow_avg_selection_score=0.69,
    ) -> dict:
        return {
            "route": route,
            "input_hash": "test",
            "shadow_offset_s": 60.0,
            "timestamp_utc": "2026-01-01T12:00:00+00:00",
            "shadow_error": shadow_error,
            "prod_latency_ms": 10.0,
            "shadow_latency_ms": 11.0,
            "prod_row_count": prod_row_count,
            "shadow_row_count": shadow_row_count,
            "prod_unique_ids": 5,
            "shadow_unique_ids": 4,
            "prod_avg_confidence": prod_avg_confidence,
            "shadow_avg_confidence": shadow_avg_confidence,
            "prod_avg_selection_score": prod_avg_selection_score,
            "shadow_avg_selection_score": shadow_avg_selection_score,
            "confidence_delta": confidence_delta,
            "selection_score_delta": selection_score_delta,
        }

    def test_pass_all_within_thresholds(self):
        records = [self._make_record(confidence_delta=0.05, shadow_row_count=9)]
        metrics = cs.compute_metrics(records)
        passed, failures = cs.evaluate(metrics, cs.THRESHOLDS)
        assert passed is True
        assert failures == []

    def test_fail_confidence_delta_too_large(self):
        records = [self._make_record(confidence_delta=0.15)]
        metrics = cs.compute_metrics(records)
        passed, failures = cs.evaluate(metrics, cs.THRESHOLDS)
        assert passed is False
        assert any("confidence_delta_mean" in f for f in failures)

    def test_fail_selection_score_delta_too_large(self):
        records = [
            self._make_record(route="/iep3", selection_score_delta=0.20)
        ]
        metrics = cs.compute_metrics(records)
        passed, failures = cs.evaluate(metrics, cs.THRESHOLDS)
        assert passed is False
        assert any("selection_score_delta_mean" in f for f in failures)

    def test_fail_high_shadow_error_rate(self):
        good   = [self._make_record() for _ in range(7)]
        errors = [self._make_record(shadow_error="RuntimeError") for _ in range(3)]
        metrics = cs.compute_metrics(good + errors)
        passed, failures = cs.evaluate(metrics, cs.THRESHOLDS)
        assert passed is False
        assert any("shadow_error_rate" in f for f in failures)

    def test_fail_row_count_ratio_too_low(self):
        # shadow returned almost nothing vs production
        records = [self._make_record(prod_row_count=100, shadow_row_count=5)]
        metrics = cs.compute_metrics(records)
        passed, failures = cs.evaluate(metrics, cs.THRESHOLDS)
        assert passed is False
        assert any("row_count_ratio_min" in f for f in failures)

    def test_empty_records_vacuously_pass(self):
        metrics = cs.compute_metrics([])
        passed, failures = cs.evaluate(metrics, cs.THRESHOLDS)
        assert passed is True
        assert failures == []

    def test_smoke_thresholds_always_pass_on_bad_data(self):
        """Smoke thresholds are so loose that even terrible data passes."""
        records = [
            self._make_record(confidence_delta=0.99, shadow_error="RuntimeError",
                              prod_row_count=100, shadow_row_count=0)
        ]
        metrics = cs.compute_metrics(records)
        passed, failures = cs.evaluate(metrics, cs.SMOKE_THRESHOLDS)
        assert passed is True

    def test_compute_metrics_confidence_delta_mean(self):
        """confidence_delta_mean averages only /tracking route records."""
        records = [
            self._make_record(route="/tracking", confidence_delta=0.04),
            self._make_record(route="/tracking", confidence_delta=0.06),
            self._make_record(route="/iep3",     confidence_delta=0.99),  # ignored
        ]
        metrics = cs.compute_metrics(records)
        assert abs(metrics["confidence_delta_mean"] - 0.05) < 1e-5

    def test_compute_metrics_selection_score_delta_mean(self):
        """selection_score_delta_mean averages only /iep3 route records."""
        records = [
            self._make_record(route="/iep3", selection_score_delta=0.10),
            self._make_record(route="/iep3", selection_score_delta=0.20),
            self._make_record(route="/tracking", selection_score_delta=0.99),  # ignored
        ]
        metrics = cs.compute_metrics(records)
        assert abs(metrics["selection_score_delta_mean"] - 0.15) < 1e-5

    def test_compute_metrics_shadow_error_rate(self):
        records = [
            self._make_record(shadow_error="none"),
            self._make_record(shadow_error="none"),
            self._make_record(shadow_error="RuntimeError"),
            self._make_record(shadow_error="TimeoutError"),
        ]
        metrics = cs.compute_metrics(records)
        assert abs(metrics["shadow_error_rate"] - 0.5) < 1e-5

    def test_compute_metrics_row_count_ratio_min(self):
        """row_count_ratio_min picks the smallest shadow/prod ratio."""
        records = [
            self._make_record(prod_row_count=10, shadow_row_count=9),   # ratio 0.9
            self._make_record(prod_row_count=10, shadow_row_count=2),   # ratio 0.2
            self._make_record(prod_row_count=10, shadow_row_count=10),  # ratio 1.0
        ]
        metrics = cs.compute_metrics(records)
        assert abs(metrics["row_count_ratio_min"] - 0.2) < 1e-5

    def test_fallback_file_loading(self, tmp_path):
        """_load_from_fallback reads records written by compare_shadow logic."""
        fallback = str(tmp_path / "shadow.jsonl")
        # Write two records with timestamps in the last hour
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        rec_a = self._make_record(route="/tracking")
        rec_b = self._make_record(route="/iep3")
        rec_a["timestamp_utc"] = ts
        rec_b["timestamp_utc"] = ts

        with open(fallback, "w") as f:
            f.write(json.dumps(rec_a) + "\n")
            f.write(json.dumps(rec_b) + "\n")

        records = cs._load_from_fallback(fallback, hours=1)
        assert len(records) == 2

    def test_fallback_file_filters_old_records(self, tmp_path):
        """Records older than the window are excluded."""
        fallback = str(tmp_path / "shadow.jsonl")
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        rec = self._make_record()
        rec["timestamp_utc"] = old_ts
        with open(fallback, "w") as f:
            f.write(json.dumps(rec) + "\n")

        records = cs._load_from_fallback(fallback, hours=24)
        assert len(records) == 0

    def test_main_returns_0_on_pass(self, tmp_path):
        """main() returns 0 when all metrics pass."""
        fallback = str(tmp_path / "shadow.jsonl")
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        rec = self._make_record(confidence_delta=0.01)
        rec["timestamp_utc"] = ts
        with open(fallback, "w") as f:
            f.write(json.dumps(rec) + "\n")

        with patch.object(cs, "_log_comparison_result"):
            exit_code = cs.main(["--fallback", fallback, "--hours", "1"])
        assert exit_code == 0

    def test_main_returns_1_on_fail(self, tmp_path):
        """main() returns 1 when a threshold is breached."""
        fallback = str(tmp_path / "shadow.jsonl")
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        rec = self._make_record(confidence_delta=0.50)  # way above threshold
        rec["timestamp_utc"] = ts
        with open(fallback, "w") as f:
            f.write(json.dumps(rec) + "\n")

        with patch.object(cs, "_log_comparison_result"):
            exit_code = cs.main(["--fallback", fallback, "--hours", "1"])
        assert exit_code == 1

    def test_main_smoke_always_returns_0(self, tmp_path):
        """--smoke flag forces exit 0 regardless of metric values."""
        fallback = str(tmp_path / "shadow.jsonl")
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        rec = self._make_record(confidence_delta=0.99)
        rec["timestamp_utc"] = ts
        with open(fallback, "w") as f:
            f.write(json.dumps(rec) + "\n")

        with patch.object(cs, "_log_comparison_result"):
            exit_code = cs.main(["--fallback", fallback, "--hours", "1", "--smoke"])
        assert exit_code == 0
