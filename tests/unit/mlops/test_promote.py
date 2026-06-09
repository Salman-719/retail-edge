"""Unit tests for the MLflow promotion ladder.

Test groups
-----------
1. promote.py — each transition function calls the right registry methods
   and logs to promotion_ladder experiment.
2. run_promotion.py — orchestration halts and rolls back on step failure.
3. check_state.py — detects and reports registry/env inconsistencies.
"""
from __future__ import annotations

import os
import sys
import tempfile
from types import ModuleType
from unittest.mock import MagicMock, call, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_mv(version: str, stage: str = "None", tags: dict | None = None):
    """Return a fake MLflow ModelVersion object."""
    mv = MagicMock()
    mv.version       = version
    mv.current_stage = stage
    mv.tags          = tags or {}
    mv.description   = ""
    return mv


def _make_client(
    version: str = "3",
    stage: str = "Staging",
    tags: dict | None = None,
):
    """Return a MagicMock MlflowClient pre-configured with one model version."""
    client = MagicMock()
    mv = _make_mv(version, stage, tags)
    client.get_model_version.return_value = mv
    client.get_latest_versions.return_value = [mv]
    client.search_model_versions.return_value = [mv]
    return client, mv


# ── Group 1: promote.py transition functions ───────────────────────────────────

class TestMoveToShadow:
    def test_transitions_stage_to_none(self):
        import promote
        client, mv = _make_client(version="3", stage="Staging")
        mv.tags = {}
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.move_to_shadow("retailvision", "3")
        client.transition_model_version_stage.assert_called_once_with(
            name="retailvision", version="3", stage="None",
            archive_existing_versions=False,
        )

    def test_sets_shadow_tag(self):
        import promote
        client, mv = _make_client(version="3", stage="Staging")
        mv.tags = {}
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.move_to_shadow("retailvision", "3")
        client.set_model_version_tag.assert_any_call(
            "retailvision", "3", "promotion_state", "shadow"
        )

    def test_logs_transition(self):
        import promote
        client, mv = _make_client(version="3", stage="Staging")
        mv.tags = {}
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition") as mock_log:
            promote.move_to_shadow("retailvision", "3", triggered_by="test")
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["to_tag"] == "shadow"
        assert kwargs["triggered_by"] == "test"
        assert kwargs["model_name"] == "retailvision"
        assert kwargs["version"] == "3"


class TestMoveToCanary:
    def test_sets_canary_tag(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "shadow"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.move_to_canary("retailvision", "3", canary_percentage=10)
        client.set_model_version_tag.assert_any_call(
            "retailvision", "3", "promotion_state", "canary"
        )

    def test_records_canary_percentage_tag(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "shadow"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.move_to_canary("retailvision", "3", canary_percentage=25)
        client.set_model_version_tag.assert_any_call(
            "retailvision", "3", "canary_percentage", "25"
        )

    def test_logs_transition_with_percentage_metric(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "shadow"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition") as mock_log:
            promote.move_to_canary("retailvision", "3", canary_percentage=15)
        kwargs = mock_log.call_args.kwargs
        assert kwargs["to_tag"] == "canary"
        assert kwargs["extra_metrics"]["canary_percentage"] == 15.0


class TestMoveToProduction:
    def test_transitions_to_production(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "canary"})
        client.get_latest_versions.return_value = []  # no existing production
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.move_to_production("retailvision", "3")
        client.transition_model_version_stage.assert_called_once_with(
            name="retailvision", version="3", stage="Production",
            archive_existing_versions=True,
        )

    def test_removes_promotion_state_tag(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "canary"})
        client.get_latest_versions.return_value = []
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.move_to_production("retailvision", "3")
        client.delete_model_version_tag.assert_called_once_with(
            "retailvision", "3", "promotion_state"
        )

    def test_tags_superseded_production_version(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "canary"})
        old_prod = _make_mv("2", "Production")
        client.get_latest_versions.return_value = [old_prod]
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.move_to_production("retailvision", "3")
        client.set_model_version_tag.assert_any_call(
            "retailvision", "2", "promotion_state", "superseded"
        )

    def test_logs_transition_to_production(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "canary"})
        client.get_latest_versions.return_value = []
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition") as mock_log:
            promote.move_to_production("retailvision", "3")
        kwargs = mock_log.call_args.kwargs
        assert kwargs["to_stage"] == "Production"


class TestRollback:
    def test_archives_version(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "shadow"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.rollback("retailvision", "3", reason="shadow failed")
        client.transition_model_version_stage.assert_called_once_with(
            name="retailvision", version="3", stage="Archived",
            archive_existing_versions=False,
        )

    def test_sets_rejected_tag(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "shadow"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.rollback("retailvision", "3", reason="shadow failed")
        client.set_model_version_tag.assert_any_call(
            "retailvision", "3", "promotion_state", "rejected"
        )

    def test_sets_rejection_reason_tag(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "canary"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.rollback("retailvision", "3", reason="canary latency too high")
        client.set_model_version_tag.assert_any_call(
            "retailvision", "3", "rejection_reason", "canary latency too high"
        )

    def test_logs_transition_with_exit_code(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "canary"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition") as mock_log:
            promote.rollback("retailvision", "3", reason="failed", eval_exit_code=1)
        kwargs = mock_log.call_args.kwargs
        assert kwargs["to_stage"] == "Archived"
        assert kwargs["extra_metrics"]["eval_exit_code"] == 1.0

    def test_updates_description_with_reason(self):
        import promote
        client, mv = _make_client(version="3", stage="None", tags={"promotion_state": "shadow"})
        with patch.object(promote, "_client", return_value=client), \
             patch.object(promote, "_log_transition"):
            promote.rollback("retailvision", "3", reason="confidence too low")
        call_args = client.update_model_version.call_args
        assert "confidence too low" in call_args.kwargs.get("description", "")


# ── Group 2: run_promotion.py orchestration ────────────────────────────────────

class TestRunPromotion:
    """Tests that the orchestrator halts and rolls back on step failure."""

    def _staging_client(self, version="3"):
        """Return a MlflowClient mock with one version in Staging."""
        client = MagicMock()
        mv = _make_mv(version, "Staging")
        client.get_latest_versions.return_value = [mv]
        return client

    def test_no_staging_version_exits_0(self):
        import run_promotion
        client = MagicMock()
        client.get_latest_versions.return_value = []
        client.search_registered_models.return_value = []
        with patch.object(run_promotion, "_mlflow_client", return_value=client):
            rc = run_promotion.main(["--model-name", "retailvision", "--dry-run"])
        assert rc == 0

    def test_shadow_failure_halts_and_returns_1(self):
        import run_promotion
        client = self._staging_client()
        with (
            patch.object(run_promotion, "_mlflow_client", return_value=client),
            patch.object(run_promotion, "_step_shadow", return_value=False) as mock_shadow,
            patch.object(run_promotion, "_step_canary") as mock_canary,
            patch.object(run_promotion, "_step_promote") as mock_promote,
        ):
            rc = run_promotion.main(["--model-name", "retailvision", "--dry-run"])
        assert rc == 1
        mock_shadow.assert_called_once()
        mock_canary.assert_not_called()
        mock_promote.assert_not_called()

    def test_canary_failure_halts_and_returns_1(self):
        import run_promotion
        client = self._staging_client()
        with (
            patch.object(run_promotion, "_mlflow_client", return_value=client),
            patch.object(run_promotion, "_step_shadow", return_value=True),
            patch.object(run_promotion, "_step_canary", return_value=False) as mock_canary,
            patch.object(run_promotion, "_step_promote") as mock_promote,
        ):
            rc = run_promotion.main(["--model-name", "retailvision", "--dry-run"])
        assert rc == 1
        mock_canary.assert_called_once()
        mock_promote.assert_not_called()

    def test_full_success_returns_0(self):
        import run_promotion
        client = self._staging_client()
        with (
            patch.object(run_promotion, "_mlflow_client", return_value=client),
            patch.object(run_promotion, "_step_shadow", return_value=True),
            patch.object(run_promotion, "_step_canary", return_value=True),
            patch.object(run_promotion, "_step_promote") as mock_promote,
        ):
            rc = run_promotion.main(["--model-name", "retailvision", "--dry-run"])
        assert rc == 0
        mock_promote.assert_called_once()

    def test_shadow_step_calls_rollback_on_subprocess_fail(self):
        """_step_shadow calls promote.rollback when compare_shadow exits non-zero."""
        import run_promotion
        import promote

        client, mv = _make_client("3", "Staging")
        mv.tags = {}

        with (
            patch.object(run_promotion, "_run_subprocess", return_value=1),
            patch.object(run_promotion, "time") as mock_time,
            patch.object(promote, "_client", return_value=client),
            patch.object(promote, "_log_transition"),
            patch.object(run_promotion, "_log_step"),
        ):
            mock_time.sleep = MagicMock()
            result = run_promotion._step_shadow("retailvision", "3")

        assert result is False
        # rollback must have archived the version
        client.transition_model_version_stage.assert_any_call(
            name="retailvision", version="3", stage="Archived",
            archive_existing_versions=False,
        )

    def test_canary_step_calls_rollback_on_subprocess_fail(self):
        """_step_canary calls promote.rollback when canary_eval exits non-zero."""
        import run_promotion
        import promote

        client, mv = _make_client("3", "None", tags={"promotion_state": "shadow"})

        with (
            patch.object(run_promotion, "_run_subprocess", return_value=1),
            patch.object(run_promotion, "time") as mock_time,
            patch.object(promote, "_client", return_value=client),
            patch.object(promote, "_log_transition"),
            patch.object(run_promotion, "_log_step"),
        ):
            mock_time.sleep = MagicMock()
            result = run_promotion._step_canary("retailvision", "3")

        assert result is False
        client.transition_model_version_stage.assert_any_call(
            name="retailvision", version="3", stage="Archived",
            archive_existing_versions=False,
        )

    def test_oldest_staging_version_selected(self):
        """When multiple Staging versions exist, the oldest (lowest int) is chosen."""
        import run_promotion
        client = MagicMock()
        mv5 = _make_mv("5", "Staging")
        mv3 = _make_mv("3", "Staging")
        mv7 = _make_mv("7", "Staging")
        client.get_latest_versions.return_value = [mv5, mv7, mv3]

        version = run_promotion._find_staging_version(client, "retailvision")
        assert version == "3"


# ── Group 3: check_state.py ────────────────────────────────────────────────────

class TestCheckState:
    """State consistency check detects and reports inconsistencies."""

    def _client_with(
        self,
        prod_versions=None,
        staging_versions=None,
        all_versions=None,
    ):
        client = MagicMock()

        def get_latest(name, stages):
            if "Production" in stages:
                return prod_versions or []
            if "Staging" in stages:
                return staging_versions or []
            return []

        client.get_latest_versions.side_effect = get_latest
        client.search_model_versions.return_value = all_versions or []
        client.search_registered_models.return_value = []
        return client

    def test_canary_tag_without_canary_percentage(self):
        import check_state
        canary_mv = _make_mv("3", "None", tags={"promotion_state": "canary"})
        prod_mv   = _make_mv("2", "Production")
        client    = self._client_with(
            prod_versions=[prod_mv],
            all_versions=[canary_mv, prod_mv],
        )
        with (
            patch.object(check_state, "_mlflow_client", return_value=client),
            patch.object(check_state, "_effective_canary_percentage", return_value=0),
        ):
            issues = check_state.run_checks("retailvision")
        assert any("canary" in i and "CANARY_PERCENTAGE=0" in i for i in issues)

    def test_canary_percentage_without_canary_tag(self):
        import check_state
        prod_mv = _make_mv("2", "Production")
        client  = self._client_with(prod_versions=[prod_mv], all_versions=[prod_mv])
        with (
            patch.object(check_state, "_mlflow_client", return_value=client),
            patch.object(check_state, "_effective_canary_percentage", return_value=10),
        ):
            issues = check_state.run_checks("retailvision")
        assert any("CANARY_PERCENTAGE=10" in i and "no model version" in i for i in issues)

    def test_stale_canary_older_than_production(self):
        import check_state
        canary_mv = _make_mv("1", "None", tags={"promotion_state": "canary"})
        prod_mv   = _make_mv("5", "Production")
        client    = self._client_with(
            prod_versions=[prod_mv],
            all_versions=[canary_mv, prod_mv],
        )
        with (
            patch.object(check_state, "_mlflow_client", return_value=client),
            patch.object(check_state, "_effective_canary_percentage", return_value=10),
        ):
            issues = check_state.run_checks("retailvision")
        # Stale canary check should fire.
        assert any("older" in i or "stale" in i for i in issues)

    def test_no_production_no_candidates_flagged(self):
        import check_state
        client = self._client_with(prod_versions=[], staging_versions=[], all_versions=[])
        with (
            patch.object(check_state, "_mlflow_client", return_value=client),
            patch.object(check_state, "_effective_canary_percentage", return_value=0),
        ):
            issues = check_state.run_checks("retailvision")
        assert any("No Production version" in i for i in issues)

    def test_clean_state_no_issues(self):
        """Production model, no canary, CANARY_PERCENTAGE=0 → no issues."""
        import check_state
        prod_mv = _make_mv("2", "Production")
        client  = self._client_with(prod_versions=[prod_mv], all_versions=[prod_mv])
        with (
            patch.object(check_state, "_mlflow_client", return_value=client),
            patch.object(check_state, "_effective_canary_percentage", return_value=0),
        ):
            issues = check_state.run_checks("retailvision")
        assert issues == []

    def test_active_canary_with_matching_percentage_no_issues(self):
        """Canary tag + CANARY_PERCENTAGE=10 + prod → expected state, no issues."""
        import check_state
        prod_mv   = _make_mv("2", "Production")
        canary_mv = _make_mv("3", "None", tags={"promotion_state": "canary"})
        client    = self._client_with(
            prod_versions=[prod_mv],
            all_versions=[prod_mv, canary_mv],
        )
        with (
            patch.object(check_state, "_mlflow_client", return_value=client),
            patch.object(check_state, "_effective_canary_percentage", return_value=10),
        ):
            issues = check_state.run_checks("retailvision")
        assert issues == []

    def test_registry_unreachable_raises_runtime_error(self):
        import check_state
        client = MagicMock()
        client.search_registered_models.side_effect = Exception("connection refused")
        with patch.object(check_state, "_mlflow_client", return_value=client):
            with pytest.raises(RuntimeError, match="Cannot reach"):
                check_state.run_checks("retailvision")

    def test_main_returns_2_on_registry_error(self):
        import check_state
        with patch.object(check_state, "run_checks", side_effect=RuntimeError("down")):
            rc = check_state.main(["--model-name", "retailvision"])
        assert rc == 2

    def test_main_returns_1_on_inconsistency(self):
        import check_state
        with patch.object(check_state, "run_checks", return_value=["something wrong"]):
            rc = check_state.main(["--model-name", "retailvision"])
        assert rc == 1

    def test_main_returns_0_on_clean(self):
        import check_state
        with patch.object(check_state, "run_checks", return_value=[]):
            rc = check_state.main(["--model-name", "retailvision"])
        assert rc == 0

    def test_env_canary_file_overrides_percentage(self):
        """CANARY_PERCENTAGE in .env.canary takes precedence over env var."""
        import check_state
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, ".env.canary")
            with open(env_file, "w") as f:
                f.write("CANARY_PERCENTAGE=0\n")
            with (
                patch.object(check_state, "CANARY_ENV_FILE", env_file),
                patch.dict(os.environ, {"CANARY_PERCENTAGE": "20"}),
            ):
                pct = check_state._effective_canary_percentage()
        assert pct == 0
