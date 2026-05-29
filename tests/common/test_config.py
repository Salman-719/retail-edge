"""Foundation tests for common.config."""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

import common.config as config_module
from common.config import Settings, get_settings


def test_defaults_match_spec():
    s = Settings()
    assert s.batch_window_seconds == 60
    assert s.embedding_dim == 512
    assert s.reid_match_threshold == 0.75
    assert s.max_walking_speed_mps == 1.5
    assert s.lost_pool_ttl_batches == 5
    assert s.global_grace_batches == 5
    assert s.selection_weight_bbox_area == 0.7
    assert s.selection_weight_confidence == 0.3


def test_env_override(monkeypatch):
    monkeypatch.setenv("REID_MATCH_THRESHOLD", "0.9")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@db:5432/test")
    s = Settings()
    assert s.reid_match_threshold == 0.9
    assert s.DATABASE_URL.endswith("/test")


def test_invalid_value_raises(monkeypatch):
    monkeypatch.setenv("REID_MATCH_THRESHOLD", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_singleton(monkeypatch):
    # reset module-level cache so the test is isolated
    importlib.reload(config_module)
    first = config_module.get_settings()
    second = config_module.get_settings()
    assert first is second
