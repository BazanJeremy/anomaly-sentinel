"""
Shared pytest configuration for Anomaly Sentinel test suite.

Defines markers, fixtures, and sector-level parametrization
available across all test modules.
"""

import os
from collections.abc import MutableMapping

import pytest

LIVE_OPT_IN = "RUN_LIVE_API_TESTS"


def strip_api_key(environ: MutableMapping[str, str]) -> bool:
    """Remove ``ANTHROPIC_API_KEY`` unless live runs were asked for.

    Returns True when a key was removed. A key present for another tool must
    not turn a free test run into hundreds of billed calls: live Claude calls
    need ``RUN_LIVE_API_TESTS=1`` as well as the key.
    """
    if environ.get(LIVE_OPT_IN) == "1":
        return False
    return environ.pop("ANTHROPIC_API_KEY", None) is not None


# Runs when pytest imports this conftest, which is before it imports any test
# module or ``src.dashboard.app``: all three read the key at import time.
strip_api_key(os.environ)


def pytest_configure(config):
    config.addinivalue_line("markers", "fintech: Fintech/banking sector tests")
    config.addinivalue_line("markers", "medtech: Medical/health sector tests")
    config.addinivalue_line("markers", "ai_behaviour: AI classifier behaviour tests")
    config.addinivalue_line("markers", "schema: Schema contract tests")
    config.addinivalue_line("markers", "slow: Tests that call external APIs (skip in fast mode)")


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests by their directory."""
    for item in items:
        path = str(item.fspath)
        if "fintech" in path or "test_fintech" in path:
            item.add_marker(pytest.mark.fintech)
        if "medtech" in path or "test_medtech" in path:
            item.add_marker(pytest.mark.medtech)
        if "ai_behaviour" in path:
            item.add_marker(pytest.mark.ai_behaviour)
        if "test_" in path and "schema" in path:
            item.add_marker(pytest.mark.schema)
