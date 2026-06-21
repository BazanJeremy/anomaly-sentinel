"""
E2E test configuration — Flask test server lifecycle.

Spins up the Flask app in a background thread before the E2E session
and tears it down after. Playwright tests connect to this local server.

No external process needed — the server starts and stops within pytest.
"""

from __future__ import annotations

import threading
import time

import pytest
import requests
from playwright.sync_api import Page, sync_playwright

from src.dashboard.app import app as flask_app

BASE_URL = "http://127.0.0.1:5001"


def _wait_for_server(url: str, timeout: int = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/api/health", timeout=1)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            time.sleep(0.1)
    raise RuntimeError(f"Flask server did not start within {timeout}s at {url}")


@pytest.fixture(scope="session")
def live_server():
    """Start Flask on port 5001 for the E2E session."""
    flask_app.config["TESTING"] = True
    server = threading.Thread(
        target=lambda: flask_app.run(port=5001, debug=False, use_reloader=False),
        daemon=True,
    )
    server.start()
    _wait_for_server(BASE_URL)
    yield BASE_URL
    # Daemon thread — auto-killed when pytest exits


@pytest.fixture(scope="session")
def browser_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture()
def page(live_server, browser_session):
    """Fresh page per test — no shared state between tests."""
    context = browser_session.new_context(base_url=live_server)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture()
def api_client(live_server):
    """Simple requests session pointed at the live server."""
    session = requests.Session()
    session.base_url = live_server

    class _Client:
        def get(self, path, **kw):
            return session.get(f"{live_server}{path}", **kw)
        def post(self, path, **kw):
            return session.post(f"{live_server}{path}", **kw)

    return _Client()
