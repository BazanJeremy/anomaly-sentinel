"""
Medtech AI classifier behaviour tests.

Same structure as the Fintech suite — same quality gate, same dual-mode
(fallback / LLM), same confidence calibration tests. This parallel
structure is intentional: it demonstrates that the test framework
is sector-agnostic, which is a key architectural claim.

Additional Medtech-specific tests:
  - Zero missed critical alerts (recall = 100% on critical-severity scenarios)
  - Sensor fault classified as technical, not clinical anomaly
  - Medication context influences reasoning (spot-check)
"""

from __future__ import annotations

import os
import pytest

from src.ai_engine.classifier import classify_vital_signs, evaluate_batch
from src.ai_engine.models import AnomalyResult, Severity
from src.simulators.medtech.generator import (
    SCENARIO_LABELS,
    generate_batch,
    generate_mixed_dataset,
    generate_vital_scenario,
)

USE_FALLBACK = not bool(os.getenv("ANTHROPIC_API_KEY"))
PROMPT_VERSION = "v1.0"


@pytest.fixture(scope="module")
def stable_corpus():
    return generate_batch("stable_routine", n=50)


@pytest.fixture(scope="module")
def mixed_dataset_small():
    return generate_mixed_dataset(n_per_scenario=5)


# ---------------------------------------------------------------------------
# 1. Single-scenario correctness
# ---------------------------------------------------------------------------

class TestMedtechSingleScenarioCorrectness:

    @pytest.mark.parametrize("scenario,expected_anomaly,expected_severity", [
        ("spo2_desaturation",    True,  "critical"),
        ("hypertensive_crisis",  True,  "high"),
        ("bradycardia_event",    True,  "high"),
        ("hypoglycaemia_alert",  True,  "medium"),
        ("sensor_drift",         True,  "medium"),
        ("stable_routine",       False, None),
    ])
    def test_scenario_detection(self, scenario, expected_anomaly, expected_severity):
        correct_anomaly = 0
        correct_severity = 0
        runs = 3

        for _ in range(runs):
            vs = generate_vital_scenario(scenario)
            result = classify_vital_signs(vs, prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK)

            assert isinstance(result, AnomalyResult)

            if result.is_anomaly == expected_anomaly:
                correct_anomaly += 1
            if expected_severity is None:
                if result.severity is None:
                    correct_severity += 1
            elif result.severity and result.severity.value == expected_severity:
                correct_severity += 1

        assert correct_anomaly == runs, f"'{scenario}': anomaly detection failed {runs - correct_anomaly}/{runs} runs"
        assert correct_severity == runs, f"'{scenario}': severity wrong {runs - correct_severity}/{runs} runs"


# ---------------------------------------------------------------------------
# 2. Zero missed critical alerts — the key Medtech safety requirement
# ---------------------------------------------------------------------------

class TestMedtechZeroMissedCritical:
    """
    In a clinical setting, missing a critical alert can cost a patient's life.
    Recall must be 100% on critical-severity scenarios.
    This test would be cited in an IEC 62304 hazard analysis.
    """

    def test_spo2_desaturation_never_missed(self):
        """SpO2 desaturation is always critical — zero misses allowed."""
        misses = []
        for i in range(10):
            vs = generate_vital_scenario("spo2_desaturation")
            result = classify_vital_signs(vs, use_fallback=USE_FALLBACK)
            if not result.is_anomaly:
                misses.append({"run": i, "spo2": vs.spo2_pct, "reason": result.reason})

        assert len(misses) == 0, (
            f"CRITICAL: {len(misses)} SpO2 desaturation events were missed:\n"
            + "\n".join(str(m) for m in misses)
        )

    def test_critical_severity_scenarios_recall_100pct(self):
        """All scenarios labeled 'critical' must be detected on every run."""
        critical_scenarios = [
            s for s, label in SCENARIO_LABELS.items()
            if label.get("severity") == "critical"
        ]

        for scenario in critical_scenarios:
            for run in range(5):
                vs = generate_vital_scenario(scenario)
                result = classify_vital_signs(vs, use_fallback=USE_FALLBACK)
                assert result.is_anomaly, (
                    f"Critical scenario '{scenario}' missed on run {run}. "
                    f"Reason: {result.reason}"
                )
                assert result.severity == Severity.CRITICAL, (
                    f"Critical scenario '{scenario}' severity downgraded to {result.severity}"
                )


# ---------------------------------------------------------------------------
# 3. False positive rate
# ---------------------------------------------------------------------------

class TestMedtechFalsePositiveRate:
    """
    Clinical alert fatigue is real — too many false alarms cause nurses
    to disable monitoring or ignore alerts. FP rate must stay <= 5%.
    """

    def test_fp_rate_under_5pct_on_stable_corpus(self, stable_corpus):
        false_positives = 0
        for vs in stable_corpus:
            result = classify_vital_signs(vs, prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK)
            if result.is_anomaly:
                false_positives += 1

        fp_rate = false_positives / len(stable_corpus)
        assert fp_rate <= 0.05, (
            f"Medtech FP rate {fp_rate:.1%} exceeds 5% quality gate "
            f"({false_positives}/{len(stable_corpus)} false positives on stable patients)"
        )


# ---------------------------------------------------------------------------
# 4. Batch precision / recall / quality gate
# ---------------------------------------------------------------------------

class TestMedtechBatchMetrics:

    def test_batch_precision_above_threshold(self, mixed_dataset_small):
        metrics = evaluate_batch(
            mixed_dataset_small, sector="medtech",
            prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK,
        )
        assert metrics.precision >= 0.85, f"Precision {metrics.precision:.1%} below 85%\n{metrics.summary()}"

    def test_batch_recall_above_threshold(self, mixed_dataset_small):
        metrics = evaluate_batch(
            mixed_dataset_small, sector="medtech",
            prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK,
        )
        assert metrics.recall >= 0.85, f"Recall {metrics.recall:.1%} below 85%\n{metrics.summary()}"

    def test_quality_gate_passes(self, mixed_dataset_small):
        metrics = evaluate_batch(
            mixed_dataset_small, sector="medtech",
            prompt_version=PROMPT_VERSION, use_fallback=USE_FALLBACK,
        )
        assert metrics.passes_quality_gate(), f"Quality gate FAILED:\n{metrics.summary()}"


# ---------------------------------------------------------------------------
# 5. Output schema validation
# ---------------------------------------------------------------------------

class TestMedtechOutputSchema:

    def test_result_is_anomaly_result_instance(self):
        vs = generate_vital_scenario("stable_routine")
        result = classify_vital_signs(vs, use_fallback=USE_FALLBACK)
        assert isinstance(result, AnomalyResult)

    def test_confidence_in_valid_range(self):
        for scenario in ["stable_routine", "spo2_desaturation", "sensor_drift"]:
            for _ in range(3):
                vs = generate_vital_scenario(scenario)
                result = classify_vital_signs(vs, use_fallback=USE_FALLBACK)
                assert 0.0 <= result.confidence <= 1.0

    def test_severity_null_for_stable_patient(self):
        for _ in range(5):
            vs = generate_vital_scenario("stable_routine")
            result = classify_vital_signs(vs, use_fallback=USE_FALLBACK)
            if not result.is_anomaly:
                assert result.severity is None

    def test_sensor_fault_is_anomaly_not_clinical_emergency(self):
        """
        Sensor drift must be flagged as an anomaly (technical issue)
        but must NOT receive critical severity (that would trigger a clinical emergency response).
        """
        for _ in range(5):
            vs = generate_vital_scenario("sensor_drift")
            result = classify_vital_signs(vs, use_fallback=USE_FALLBACK)
            assert result.is_anomaly, "Sensor fault must be flagged"
            assert result.severity != Severity.CRITICAL, (
                "Sensor fault must not trigger a critical clinical alert"
            )


# ---------------------------------------------------------------------------
# 6. Confidence calibration
# ---------------------------------------------------------------------------

class TestMedtechConfidenceCalibration:

    def test_high_confidence_predictions_are_correct(self):
        misclassified = []
        for scenario, label in SCENARIO_LABELS.items():
            for _ in range(3):
                vs = generate_vital_scenario(scenario)
                result = classify_vital_signs(vs, use_fallback=USE_FALLBACK)
                if result.confidence >= 0.85 and result.is_anomaly != label["is_anomaly"]:
                    misclassified.append({
                        "scenario": scenario,
                        "confidence": result.confidence,
                        "predicted": result.is_anomaly,
                        "expected": label["is_anomaly"],
                    })

        assert len(misclassified) == 0, (
            f"High-confidence misclassifications:\n"
            + "\n".join(str(m) for m in misclassified)
        )
