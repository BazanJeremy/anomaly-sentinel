"""
Anomaly Sentinel — Flask dashboard.

Exposes the anomaly classifier via REST API and a minimal UI.
This module is the E2E test surface for Playwright tests in tests/e2e/.

Endpoints:
  GET  /                          → Dashboard UI
  GET  /api/health                → Health check
  GET  /api/scenarios             → List available scenarios per sector
  POST /api/classify              → Classify a single generated scenario
  POST /api/batch                 → Run batch evaluation and return metrics
  GET  /api/metrics               → Last batch metrics (cached in-process)

Design note: the app intentionally avoids a database to stay zero-dependency.
State is held in module-level dicts — fine for a demo context.
In a production system this would be replaced by a proper metrics store.
"""

from __future__ import annotations

import os
import time
from typing import Any

from flask import Flask, jsonify, render_template, request

from src.ai_engine.classifier import classify_transaction, classify_vital_signs, evaluate_batch
from src.ai_engine.models import ClassificationMetrics
from src.simulators.fintech.generator import (
    SCENARIO_LABELS as FINTECH_LABELS,
    generate_fraud_scenario,
    generate_mixed_dataset as fintech_mixed,
)
from src.simulators.medtech.generator import (
    SCENARIO_LABELS as MEDTECH_LABELS,
    generate_vital_scenario,
    generate_mixed_dataset as medtech_mixed,
)

app = Flask(__name__)
app.config["TESTING"] = False

USE_FALLBACK = not bool(os.getenv("ANTHROPIC_API_KEY"))

# In-process metrics cache — keyed by sector
_metrics_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _metrics_to_dict(m: ClassificationMetrics) -> dict:
    return {
        "sector": m.sector,
        "prompt_version": m.prompt_version,
        "total": m.total,
        "true_positives": m.true_positives,
        "true_negatives": m.true_negatives,
        "false_positives": m.false_positives,
        "false_negatives": m.false_negatives,
        "precision": round(m.precision, 4),
        "recall": round(m.recall, 4),
        "f1_score": round(m.f1_score, 4),
        "false_positive_rate": round(m.false_positive_rate, 4),
        "passes_quality_gate": m.passes_quality_gate(),
        "summary": m.summary(),
    }


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "mode": "fallback" if USE_FALLBACK else "llm",
        "sectors": ["fintech", "medtech"],
    })


@app.route("/api/scenarios")
def list_scenarios():
    sector = request.args.get("sector", "all")
    result: dict[str, Any] = {}

    if sector in ("fintech", "all"):
        result["fintech"] = [
            {"name": name, "is_anomaly": label["is_anomaly"], "severity": label["severity"]}
            for name, label in FINTECH_LABELS.items()
        ]
    if sector in ("medtech", "all"):
        result["medtech"] = [
            {"name": name, "is_anomaly": label["is_anomaly"], "severity": label["severity"]}
            for name, label in MEDTECH_LABELS.items()
        ]

    return jsonify(result)


@app.route("/api/classify", methods=["POST"])
def classify():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    sector = body.get("sector")
    scenario = body.get("scenario")
    prompt_version = body.get("prompt_version", "v1.1" if sector == "fintech" else "v1.0")

    if sector not in ("fintech", "medtech"):
        return jsonify({"error": "sector must be 'fintech' or 'medtech'"}), 400
    if not scenario:
        return jsonify({"error": "scenario is required"}), 400

    try:
        t0 = time.perf_counter()
        if sector == "fintech":
            data = generate_fraud_scenario(scenario)
            result = classify_transaction(data, prompt_version=prompt_version, use_fallback=USE_FALLBACK)
            ground_truth = FINTECH_LABELS.get(scenario, {})
        else:
            data = generate_vital_scenario(scenario)
            result = classify_vital_signs(data, prompt_version=prompt_version, use_fallback=USE_FALLBACK)
            ground_truth = MEDTECH_LABELS.get(scenario, {})

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        return jsonify({
            "sector": sector,
            "scenario": scenario,
            "prompt_version": prompt_version,
            "classification": {
                "is_anomaly": result.is_anomaly,
                "severity": result.severity.value if result.severity else None,
                "confidence": result.confidence,
                "reason": result.reason,
                "rule_triggered": result.rule_triggered,
            },
            "ground_truth": ground_truth,
            "correct": result.is_anomaly == ground_truth.get("is_anomaly"),
            "latency_ms": latency_ms,
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Classification failed: {str(e)}"}), 500


@app.route("/api/batch", methods=["POST"])
def batch_evaluate():
    body = request.get_json(silent=True) or {}
    sector = body.get("sector", "fintech")
    prompt_version = body.get("prompt_version", "v1.1" if sector == "fintech" else "v1.0")
    n_per_scenario = int(body.get("n_per_scenario", 5))

    if sector not in ("fintech", "medtech"):
        return jsonify({"error": "sector must be 'fintech' or 'medtech'"}), 400

    if n_per_scenario < 1 or n_per_scenario > 20:
        return jsonify({"error": "n_per_scenario must be between 1 and 20"}), 400

    try:
        t0 = time.perf_counter()
        if sector == "fintech":
            dataset = fintech_mixed(n_per_scenario=n_per_scenario)
        else:
            dataset = medtech_mixed(n_per_scenario=n_per_scenario)

        metrics = evaluate_batch(
            dataset,
            sector=sector,
            prompt_version=prompt_version,
            use_fallback=USE_FALLBACK,
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        result = _metrics_to_dict(metrics)
        result["latency_ms"] = latency_ms

        _metrics_cache[sector] = result
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": f"Batch evaluation failed: {str(e)}"}), 500


@app.route("/api/metrics")
def get_metrics():
    sector = request.args.get("sector")
    if sector:
        if sector not in _metrics_cache:
            return jsonify({"error": f"No metrics cached for sector '{sector}'. Run /api/batch first."}), 404
        return jsonify(_metrics_cache[sector])
    return jsonify(_metrics_cache if _metrics_cache else {"message": "No metrics yet. Run /api/batch first."})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "method not allowed"}), 405


if __name__ == "__main__":
    app.run(debug=False, port=5000)
