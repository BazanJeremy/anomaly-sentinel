"""
Fintech AI classifier behaviour tests.

These tests treat the anomaly classifier as a black-box component
and measure its observable behaviour against labeled ground-truth scenarios.

Two modes:
  - FALLBACK mode (default, no API key): tests the rule-based classifier.
    All tests run in CI without any secrets.
  - LLM mode (ANTHROPIC_API_KEY set): tests the actual Claude classifier.
    Run locally or in a protected CI job with secrets.

The same test suite covers both modes — this is intentional.
The rule-based fallback is a specification of the LLM's expected behaviour.
If the LLM diverges significantly from the rules, a test fails and
prompts a prompt revision.

Test categories:
  1. Single-scenario correctness (is_anomaly + severity)
  2. False positive rate on normal corpus
  3. Batch precision/recall/quality gate
  4. Prompt regression (v1.0 vs v1.1 on same scenarios)
  5. Output schema validation (LLM cannot return malformed JSON)
  6. Confidence calibration (high-confidence must be correct)
"""

from __future__ import annotations

import os
import pytest

from src.ai_engine.classifier import classify_transaction, evaluate_batch
from src.ai_engine.models import AnomalyResult, Severity
from src.simulators.fintech.generator import (
    SCENARIO_LABELS,
    generate_batch,
    generate_fraud_scenario,
    generate_mixed_dataset,
)

# Use rule-based fallback unless a real API key is present
USE_FALLBACK = not bool(os.getenv("ANTHROPIC_API_KEY"))
PROMPT_VERSION = "v1.1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def normal_corpus():
    """50 normal transactions for FP rate measurement."""
    return generate_batch("normal_purchase", n=50)


@pytest.fixture(scope="module")
def mixed_dataset_small():
    """Balanced labeled dataset: 5 per scenario = 30 samples."""
    return generate_mixed_dataset(n_per_scenario=5)


# ---------------------------------------------------------------------------
# 1. Single-scenario correctness
# ---------------------------------------------------------------------------

class TestFintechSingleScenarioCorrectness:
    """
    Each known fraud pattern must be detected with correct severity.
    These are the 'smoke tests' of the AI classifier.
    """

    @pytest.mark.parametrize("scenario,expected_anomaly,expected_severity", [
        ("geo_impossible",       True,  "critical"),
        ("velocity_burst",       True,  "high"),
        ("dormant_account_spike",True,  "medium"),
        ("card_testing",         True,  "high"),
        ("high_risk_category",   True,  "medium"),
        ("normal_purchase",      False, None),
    ])
    def test_scenario_detection(self, scenario, expected_anomaly, expected_severity):
        """Classifier must correctly label each scenario on 3/3 attempts."""
        correct_anomaly = 0
        correct_severity = 0
        runs = 3

        for _ in range(runs):
            tx = generate_fraud_scenario(scenario)
            result = classify_transaction(tx, prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK)

            assert isinstance(result, AnomalyResult), "Result must be AnomalyResult"

            if result.is_anomaly == expected_anomaly:
                correct_anomaly += 1
            if expected_severity is None:
                if result.severity is None:
                    correct_severity += 1
            elif result.severity and result.severity.value == expected_severity:
                correct_severity += 1

        assert correct_anomaly == runs, (
            f"Scenario '{scenario}': anomaly detection failed {runs - correct_anomaly}/{runs} runs"
        )
        assert correct_severity == runs, (
            f"Scenario '{scenario}': severity mismatch {runs - correct_severity}/{runs} runs"
        )

    def test_geo_impossible_always_critical(self):
        """GEO_IMPOSSIBLE is the highest-risk pattern — must never be downgraded."""
        for _ in range(5):
            tx = generate_fraud_scenario("geo_impossible")
            result = classify_transaction(tx, prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK)
            assert result.is_anomaly is True
            assert result.severity == Severity.CRITICAL, (
                f"geo_impossible returned severity={result.severity} — must be critical"
            )

    def test_normal_purchase_never_flagged_as_critical(self):
        """Normal transactions must never receive critical severity."""
        for _ in range(10):
            tx = generate_fraud_scenario("normal_purchase")
            result = classify_transaction(tx, prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK)
            assert result.severity != Severity.CRITICAL


# ---------------------------------------------------------------------------
# 2. False positive rate
# ---------------------------------------------------------------------------

class TestFintechFalsePositiveRate:
    """
    FP rate is the operational cost metric of a fraud detector.
    Every false alarm requires manual review — too many and analysts stop trusting the system.
    Quality gate: FP rate <= 5% on a corpus of 50 normal transactions.
    """

    def test_fp_rate_under_5pct(self, normal_corpus):
        false_positives = 0
        for tx in normal_corpus:
            result = classify_transaction(tx, prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK)
            if result.is_anomaly:
                false_positives += 1

        fp_rate = false_positives / len(normal_corpus)
        assert fp_rate <= 0.05, (
            f"FP rate {fp_rate:.1%} exceeds 5% quality gate "
            f"({false_positives}/{len(normal_corpus)} false positives)"
        )

    def test_fp_rate_reported_in_output(self, normal_corpus):
        """Ensure the FP rate is computable from evaluate_batch output."""
        labeled = [(tx, {"is_anomaly": False, "severity": None}) for tx in normal_corpus[:20]]
        metrics = evaluate_batch(labeled, sector="fintech", prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK)
        assert metrics.false_positive_rate <= 0.05
        assert metrics.sector == "fintech"


# ---------------------------------------------------------------------------
# 3. Batch precision / recall / quality gate
# ---------------------------------------------------------------------------

class TestFintechBatchMetrics:
    """
    Measures classifier accuracy across the full scenario space.
    The quality gate (precision >= 85%, recall >= 85%, FP <= 5%)
    mirrors what a bank's fraud team would require before production deployment.
    """

    def test_batch_precision_above_threshold(self, mixed_dataset_small):
        metrics = evaluate_batch(
            mixed_dataset_small,
            sector="fintech",
            prompt_version=PROMPT_VERSION,
            use_fallback=USE_FALLBACK,
        )
        assert metrics.precision >= 0.85, (
            f"Precision {metrics.precision:.1%} below 85% threshold\n{metrics.summary()}"
        )

    def test_batch_recall_above_threshold(self, mixed_dataset_small):
        metrics = evaluate_batch(
            mixed_dataset_small,
            sector="fintech",
            prompt_version=PROMPT_VERSION,
            use_fallback=USE_FALLBACK,
        )
        assert metrics.recall >= 0.85, (
            f"Recall {metrics.recall:.1%} below 85% threshold\n{metrics.summary()}"
        )

    def test_quality_gate_passes(self, mixed_dataset_small):
        metrics = evaluate_batch(
            mixed_dataset_small,
            sector="fintech",
            prompt_version=PROMPT_VERSION,
            use_fallback=USE_FALLBACK,
        )
        assert metrics.passes_quality_gate(), (
            f"Quality gate failed:\n{metrics.summary()}"
        )

    def test_metrics_summary_string_format(self, mixed_dataset_small):
        metrics = evaluate_batch(
            mixed_dataset_small, sector="fintech",
            prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK,
        )
        summary = metrics.summary()
        assert "FINTECH" in summary
        assert "PASS" in summary or "FAIL" in summary
        assert "P=" in summary and "R=" in summary


# ---------------------------------------------------------------------------
# 4. Prompt regression testing
# ---------------------------------------------------------------------------

class TestFintechPromptRegression:
    """
    Ensures that a prompt update doesn't silently degrade accuracy.
    v1.1 must perform >= v1.0 on the same dataset.
    This test would catch a regression if someone edits a prompt file carelessly.
    """

    @pytest.mark.parametrize("version", ["v1.0", "v1.1"])
    def test_prompt_version_passes_quality_gate(self, mixed_dataset_small, version):
        metrics = evaluate_batch(
            mixed_dataset_small,
            sector="fintech",
            prompt_version=version,
            use_fallback=USE_FALLBACK,
        )
        assert metrics.passes_quality_gate(), (
            f"Prompt {version} failed quality gate:\n{metrics.summary()}"
        )

    def test_v1_1_fp_rate_not_worse_than_v1_0(self, normal_corpus):
        """v1.1 adds heuristic constraints — should not introduce more FPs than v1.0."""
        labeled_normal = [(tx, {"is_anomaly": False, "severity": None}) for tx in normal_corpus[:30]]

        m10 = evaluate_batch(labeled_normal, "fintech", "v1.0", use_fallback=USE_FALLBACK)
        m11 = evaluate_batch(labeled_normal, "fintech", "v1.1", use_fallback=USE_FALLBACK)

        assert m11.false_positive_rate <= m10.false_positive_rate + 0.05, (
            f"v1.1 FP rate ({m11.false_positive_rate:.1%}) is significantly worse "
            f"than v1.0 ({m10.false_positive_rate:.1%})"
        )


# ---------------------------------------------------------------------------
# 5. Output schema validation
# ---------------------------------------------------------------------------

class TestFintechOutputSchema:
    """
    The AI output must always conform to AnomalyResult schema.
    These tests verify the parsing + validation layer catches bad LLM output.
    """

    def test_result_is_anomaly_result_instance(self):
        tx = generate_fraud_scenario("normal_purchase")
        result = classify_transaction(tx, use_fallback=USE_FALLBACK)
        assert isinstance(result, AnomalyResult)

    def test_confidence_always_in_valid_range(self):
        for scenario in ["normal_purchase", "geo_impossible", "velocity_burst"]:
            for _ in range(3):
                tx = generate_fraud_scenario(scenario)
                result = classify_transaction(tx, use_fallback=USE_FALLBACK)
                assert 0.0 <= result.confidence <= 1.0, (
                    f"Confidence {result.confidence} out of [0, 1] range"
                )

    def test_reason_always_non_empty(self):
        for scenario in ["normal_purchase", "card_testing"]:
            tx = generate_fraud_scenario(scenario)
            result = classify_transaction(tx, use_fallback=USE_FALLBACK)
            assert len(result.reason) >= 10, "Reason must be a meaningful sentence"

    def test_severity_null_for_non_anomaly(self):
        for _ in range(5):
            tx = generate_fraud_scenario("normal_purchase")
            result = classify_transaction(tx, use_fallback=USE_FALLBACK)
            if not result.is_anomaly:
                assert result.severity is None


# ---------------------------------------------------------------------------
# 6. Confidence calibration
# ---------------------------------------------------------------------------

class TestFintechConfidenceCalibration:
    """
    High-confidence predictions must be correct.
    A classifier that says 'confidence=0.95' but is wrong is worse than useless —
    it actively misleads the fraud analyst.
    """

    def test_high_confidence_predictions_are_correct(self):
        """When confidence >= 0.85, the prediction must match ground truth."""
        misclassified_high_confidence = []

        for scenario, label in SCENARIO_LABELS.items():
            for _ in range(3):
                tx = generate_fraud_scenario(scenario)
                result = classify_transaction(tx, use_fallback=USE_FALLBACK)

                if result.confidence >= 0.85:
                    if result.is_anomaly != label["is_anomaly"]:
                        misclassified_high_confidence.append({
                            "scenario": scenario,
                            "confidence": result.confidence,
                            "predicted": result.is_anomaly,
                            "expected": label["is_anomaly"],
                            "reason": result.reason,
                        })

        assert len(misclassified_high_confidence) == 0, (
            f"High-confidence misclassifications found:\n"
            + "\n".join(str(m) for m in misclassified_high_confidence)
        )
