"""
Shared pytest configuration for Anomaly Sentinel test suite.

Defines markers, fixtures, and sector-level parametrization
available across all test modules.
"""

import pytest


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
