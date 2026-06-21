"""
Playwright E2E UI tests — dashboard browser interactions.

Tests the dashboard as a real user would experience it:
page loads, sector switching, scenario classification, batch metrics display.

All tests run in headless Chromium. The Flask server is managed by
the live_server fixture in conftest.py.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


class TestDashboardLoad:

    def test_page_loads_with_200(self, page: Page, live_server):
        response = page.goto("/")
        assert response.status == 200

    def test_page_title_contains_anomaly_sentinel(self, page: Page, live_server):
        page.goto("/")
        expect(page).to_have_title("Anomaly Sentinel — Dashboard")

    def test_header_visible(self, page: Page, live_server):
        page.goto("/")
        expect(page.locator("header h1")).to_be_visible()
        expect(page.locator("header h1")).to_contain_text("Anomaly Sentinel")

    def test_mode_badge_visible_after_load(self, page: Page, live_server):
        page.goto("/")
        badge = page.locator("#mode-badge")
        expect(badge).to_be_visible()
        # Badge text should be one of the two modes
        badge.wait_for(state="visible")
        page.wait_for_function("document.getElementById('mode-badge').textContent !== 'loading…'")
        badge_text = badge.inner_text()
        assert badge_text in ("LLM mode", "Fallback mode"), f"Unexpected badge: {badge_text}"

    def test_three_main_cards_visible(self, page: Page, live_server):
        page.goto("/")
        expect(page.locator("#classify-card")).to_be_visible()
        expect(page.locator("#batch-card")).to_be_visible()
        expect(page.locator("#scenarios-card")).to_be_visible()


class TestScenarioRegistry:

    def test_scenarios_table_is_populated(self, page: Page, live_server):
        page.goto("/")
        # Wait for the table to be populated by the JS fetch
        page.wait_for_function(
            "document.querySelectorAll('#scenarios-body tr').length > 0"
        )
        rows = page.locator("#scenarios-body tr").count()
        assert rows == 12, f"Expected 12 scenario rows (6+6), got {rows}"

    def test_table_has_four_columns(self, page: Page, live_server):
        page.goto("/")
        headers = page.locator("table thead th")
        expect(headers).to_have_count(4)


class TestClassifyCard:

    def test_sector_dropdown_has_two_options(self, page: Page, live_server):
        page.goto("/")
        options = page.locator("#sector-select option")
        expect(options).to_have_count(2)

    def test_scenario_dropdown_populated_on_load(self, page: Page, live_server):
        page.goto("/")
        page.wait_for_function(
            "document.querySelectorAll('#scenario-select option').length > 0"
        )
        count = page.locator("#scenario-select option").count()
        assert count == 6

    def test_classify_button_present(self, page: Page, live_server):
        page.goto("/")
        expect(page.locator("#classify-btn")).to_be_visible()
        expect(page.locator("#classify-btn")).to_be_enabled()

    def test_classify_button_triggers_result(self, page: Page, live_server):
        page.goto("/")
        # Wait for scenarios to load
        page.wait_for_function(
            "document.querySelectorAll('#scenario-select option').length > 0"
        )
        page.click("#classify-btn")
        # Result box should appear
        page.wait_for_selector("#classify-result.visible", timeout=8000)
        result_text = page.locator("#classify-result").inner_text()
        assert "is_anomaly" in result_text
        assert "confidence" in result_text

    def test_sector_switch_repopulates_scenarios(self, page: Page, live_server):
        page.goto("/")
        page.wait_for_function(
            "document.querySelectorAll('#scenario-select option').length > 0"
        )
        # Switch to medtech
        page.select_option("#sector-select", "medtech")
        page.wait_for_function(
            "document.querySelector('#scenario-select option') && "
            "document.querySelector('#scenario-select option').value !== 'normal_purchase'"
        )
        options_text = page.locator("#scenario-select").inner_text()
        assert "stable_routine" in options_text or "spo2" in options_text

    def test_result_contains_json_keys(self, page: Page, live_server):
        page.goto("/")
        page.wait_for_function(
            "document.querySelectorAll('#scenario-select option').length > 0"
        )
        # Select geo_impossible for a deterministic anomaly result
        page.select_option("#scenario-select", "geo_impossible")
        page.click("#classify-btn")
        page.wait_for_selector("#classify-result.visible", timeout=8000)
        result_text = page.locator("#classify-result").inner_text()
        for key in ["is_anomaly", "severity", "confidence", "reason", "rule_triggered"]:
            assert key in result_text, f"Key '{key}' missing from result"


class TestBatchCard:

    def test_batch_sector_dropdown_present(self, page: Page, live_server):
        page.goto("/")
        expect(page.locator("#batch-sector")).to_be_visible()

    def test_batch_n_dropdown_present(self, page: Page, live_server):
        page.goto("/")
        expect(page.locator("#batch-n")).to_be_visible()

    def test_batch_button_present_and_enabled(self, page: Page, live_server):
        page.goto("/")
        expect(page.locator("#batch-btn")).to_be_visible()
        expect(page.locator("#batch-btn")).to_be_enabled()

    def test_batch_run_shows_metrics_grid(self, page: Page, live_server):
        page.goto("/")
        page.select_option("#batch-n", "3")  # Quick run
        page.click("#batch-btn")
        # Metrics grid should appear after evaluation
        page.wait_for_selector("#metrics-grid", state="visible", timeout=15000)
        # Should have 6 metric tiles
        tiles = page.locator(".metric").count()
        assert tiles == 6, f"Expected 6 metric tiles, got {tiles}"

    def test_batch_shows_quality_gate_result(self, page: Page, live_server):
        page.goto("/")
        page.select_option("#batch-n", "3")
        page.click("#batch-btn")
        page.wait_for_selector("#metrics-grid", state="visible", timeout=15000)
        # Quality gate tile should say PASS or FAIL
        gate_text = page.locator(".metric").last.inner_text()
        assert "PASS" in gate_text or "FAIL" in gate_text

    def test_batch_summary_line_appears(self, page: Page, live_server):
        page.goto("/")
        page.select_option("#batch-n", "3")
        page.click("#batch-btn")
        page.wait_for_selector("#batch-result.visible", timeout=15000)
        summary = page.locator("#batch-result").inner_text()
        assert "P=" in summary or "Precision" in summary or "PASS" in summary or "FAIL" in summary
