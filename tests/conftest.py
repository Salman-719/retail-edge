"""Root test configuration.

Adds the `--cloud` opt-in flag and auto-skips `@pytest.mark.cloud` tests unless
both `--cloud` is passed AND CLOUD_URL is set — so the default suite (and CI) stay
green offline. See specs/robustness-qa/cross-cutting/04-qa-harness.md.
"""
import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--cloud",
        action="store_true",
        default=False,
        help="run @cloud E2E tests against the live deployed URL (requires CLOUD_URL)",
    )


def pytest_collection_modifyitems(config, items):
    run_cloud = config.getoption("--cloud") and bool(os.environ.get("CLOUD_URL"))
    if run_cloud:
        return
    skip_cloud = pytest.mark.skip(reason="cloud E2E: needs --cloud and CLOUD_URL")
    for item in items:
        if "cloud" in item.keywords:
            item.add_marker(skip_cloud)
