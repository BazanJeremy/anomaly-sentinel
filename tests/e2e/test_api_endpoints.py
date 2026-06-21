"""
REST API endpoint tests — no browser required.

Tests the Flask API contract directly via requests.
Faster than Playwright UI tests; covers all edge cases and error paths.

Categories:
  1. Health check
  2. Scenario listing
  3. Classification endpoint (happy path + error cases)
  4. Batch evaluation endpoint
  5. Metrics cache endpoint
  6. HTTP error handling (404, 405)
"""

from __future__ import annotations

import pytest


class TestHealthEndpoint:

    def test_health_returns_200(self, api_client):
        r = api_client.get("/api/health")
        assert r.status_code == 200

    def test_health_response_schema(self, api_client):
        d = api_client.get("/api/health").json()
        assert "status" in d
        assert d["status"] == "ok"
        assert "version" in d
        assert "mode" in d
        assert d["mode"] in ("llm", "fallback")
        assert "sectors" in d
        assert set(d["sectors"]) == {"fintech", "medtech"}

    def test_health_content_type_json(self, api_client):
        r = api_client.get("/api/health")
        assert "application/json" in r.headers["Content-Type"]


class TestScenariosEndpoint:

    def test_scenarios_all_returns_both_sectors(self, api_client):
        d = api_client.get("/api/scenarios").json()
        assert "fintech" in d
        assert "medtech" in d

    def test_scenarios_fintech_filter(self, api_client):
        d = api_client.get("/api/scenarios?sector=fintech").json()
        assert "fintech" in d
        assert "medtech" not in d

    def test_scenarios_medtech_filter(self, api_client):
        d = api_client.get("/api/scenarios?sector=medtech").json()
        assert "medtech" in d
        assert "fintech" not in d

    def test_fintech_has_six_scenarios(self, api_client):
        d = api_client.get("/api/scenarios?sector=fintech").json()
        assert len(d["fintech"]) == 6

    def test_medtech_has_six_scenarios(self, api_client):
        d = api_client.get("/api/scenarios?sector=medtech").json()
        assert len(d["medtech"]) == 6

    def test_scenario_objects_have_required_fields(self, api_client):
        d = api_client.get("/api/scenarios").json()
        for sector_scenarios in d.values():
            for s in sector_scenarios:
                assert "name" in s
                assert "is_anomaly" in s
                assert "severity" in s

    def test_normal_scenarios_labeled_clean(self, api_client):
        d = api_client.get("/api/scenarios").json()
        fintech_normal = next(s for s in d["fintech"] if s["name"] == "normal_purchase")
        assert fintech_normal["is_anomaly"] is False
        assert fintech_normal["severity"] is None

    def test_geo_impossible_labeled_critical(self, api_client):
        d = api_client.get("/api/scenarios").json()
        geo = next(s for s in d["fintech"] if s["name"] == "geo_impossible")
        assert geo["is_anomaly"] is True
        assert geo["severity"] == "critical"


class TestClassifyEndpoint:

    def test_classify_fintech_happy_path(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "fintech",
            "scenario": "geo_impossible",
        })
        assert r.status_code == 200
        d = r.json()
        assert "classification" in d
        assert d["classification"]["is_anomaly"] is True
        assert d["classification"]["severity"] == "critical"

    def test_classify_medtech_happy_path(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "medtech",
            "scenario": "spo2_desaturation",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["classification"]["is_anomaly"] is True
        assert d["classification"]["severity"] == "critical"

    def test_classify_normal_returns_clean(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "fintech",
            "scenario": "normal_purchase",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["classification"]["is_anomaly"] is False
        assert d["classification"]["severity"] is None

    def test_classify_response_contains_ground_truth(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "fintech",
            "scenario": "velocity_burst",
        })
        d = r.json()
        assert "ground_truth" in d
        assert d["ground_truth"]["is_anomaly"] is True

    def test_classify_response_contains_correct_flag(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "fintech",
            "scenario": "geo_impossible",
        })
        d = r.json()
        assert "correct" in d
        assert d["correct"] is True  # Fallback always correct on labeled scenarios

    def test_classify_response_contains_latency(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "fintech",
            "scenario": "normal_purchase",
        })
        d = r.json()
        assert "latency_ms" in d
        assert d["latency_ms"] >= 0

    def test_classify_confidence_in_valid_range(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "fintech",
            "scenario": "card_testing",
        })
        d = r.json()
        conf = d["classification"]["confidence"]
        assert 0.0 <= conf <= 1.0

    def test_classify_missing_body_returns_400(self, api_client):
        r = api_client.post("/api/classify", json=None,
                            headers={"Content-Type": "text/plain"})
        assert r.status_code == 400

    def test_classify_invalid_sector_returns_400(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "aerospace",
            "scenario": "normal_purchase",
        })
        assert r.status_code == 400
        assert "sector" in r.json()["error"].lower()

    def test_classify_missing_scenario_returns_400(self, api_client):
        r = api_client.post("/api/classify", json={"sector": "fintech"})
        assert r.status_code == 400

    def test_classify_unknown_scenario_returns_400(self, api_client):
        r = api_client.post("/api/classify", json={
            "sector": "fintech",
            "scenario": "unicorn_fraud_pattern",
        })
        assert r.status_code == 400

    @pytest.mark.parametrize("scenario", [
        "normal_purchase", "velocity_burst", "geo_impossible",
        "dormant_account_spike", "card_testing", "high_risk_category",
    ])
    def test_all_fintech_scenarios_classifiable(self, api_client, scenario):
        r = api_client.post("/api/classify", json={"sector": "fintech", "scenario": scenario})
        assert r.status_code == 200

    @pytest.mark.parametrize("scenario", [
        "stable_routine", "spo2_desaturation", "hypertensive_crisis",
        "bradycardia_event", "hypoglycaemia_alert", "sensor_drift",
    ])
    def test_all_medtech_scenarios_classifiable(self, api_client, scenario):
        r = api_client.post("/api/classify", json={"sector": "medtech", "scenario": scenario})
        assert r.status_code == 200


class TestBatchEndpoint:

    def test_batch_fintech_returns_200(self, api_client):
        r = api_client.post("/api/batch", json={"sector": "fintech", "n_per_scenario": 3})
        assert r.status_code == 200

    def test_batch_medtech_returns_200(self, api_client):
        r = api_client.post("/api/batch", json={"sector": "medtech", "n_per_scenario": 3})
        assert r.status_code == 200

    def test_batch_response_has_precision_recall_f1(self, api_client):
        d = api_client.post("/api/batch", json={"sector": "fintech", "n_per_scenario": 3}).json()
        assert "precision" in d
        assert "recall" in d
        assert "f1_score" in d
        assert "false_positive_rate" in d

    def test_batch_quality_gate_passes(self, api_client):
        d = api_client.post("/api/batch", json={"sector": "fintech", "n_per_scenario": 5}).json()
        assert d["passes_quality_gate"] is True, f"Quality gate FAILED: {d.get('summary')}"

    def test_batch_medtech_quality_gate_passes(self, api_client):
        d = api_client.post("/api/batch", json={"sector": "medtech", "n_per_scenario": 5}).json()
        assert d["passes_quality_gate"] is True, f"Quality gate FAILED: {d.get('summary')}"

    def test_batch_invalid_sector_returns_400(self, api_client):
        r = api_client.post("/api/batch", json={"sector": "gaming"})
        assert r.status_code == 400

    def test_batch_n_too_large_returns_400(self, api_client):
        r = api_client.post("/api/batch", json={"sector": "fintech", "n_per_scenario": 99})
        assert r.status_code == 400

    def test_batch_total_sample_count_correct(self, api_client):
        d = api_client.post("/api/batch", json={"sector": "fintech", "n_per_scenario": 4}).json()
        # 6 scenarios × 4 = 24 total
        assert d["total"] == 24

    def test_batch_populates_metrics_cache(self, api_client):
        api_client.post("/api/batch", json={"sector": "fintech", "n_per_scenario": 3})
        r = api_client.get("/api/metrics?sector=fintech")
        assert r.status_code == 200
        assert "precision" in r.json()


class TestMetricsEndpoint:

    def test_metrics_empty_before_batch(self, api_client):
        # Metrics may or may not be cached depending on test order — just check 200
        r = api_client.get("/api/metrics")
        assert r.status_code == 200

    def test_metrics_after_batch_has_data(self, api_client):
        api_client.post("/api/batch", json={"sector": "medtech", "n_per_scenario": 3})
        d = api_client.get("/api/metrics?sector=medtech").json()
        assert "precision" in d
        assert d["sector"] == "medtech"

    def test_metrics_unknown_sector_returns_404(self, api_client):
        r = api_client.get("/api/metrics?sector=nonexistent")
        assert r.status_code == 404


class TestHTTPErrorHandling:

    def test_unknown_route_returns_404_json(self, api_client):
        r = api_client.get("/api/this-does-not-exist")
        assert r.status_code == 404
        assert "error" in r.json()

    def test_classify_get_returns_405(self, api_client):
        r = api_client.get("/api/classify")
        assert r.status_code == 405
        assert "error" in r.json()

    def test_batch_get_returns_405(self, api_client):
        r = api_client.get("/api/batch")
        assert r.status_code == 405
