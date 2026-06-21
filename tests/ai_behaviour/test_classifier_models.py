"""
AnomalyResult and ClassificationMetrics model unit tests.

Tests the Pydantic validation layer that guards classifier output.
These run in <1ms each — no API calls, no fixtures.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.ai_engine.models import AnomalyResult, ClassificationMetrics, Severity


class TestAnomalyResultValidation:

    def test_valid_anomaly_result(self):
        r = AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.92,
            reason="25 transactions in 2 hours", rule_triggered="velocity",
        )
        assert r.severity == Severity.HIGH
        assert r.is_high_risk is True

    def test_valid_clean_result(self):
        r = AnomalyResult(
            is_anomaly=False, severity=None, confidence=0.88,
            reason="All signals within normal parameters", rule_triggered="none",
        )
        assert r.severity is None
        assert r.is_high_risk is False

    def test_severity_set_when_not_anomaly_rejected(self):
        with pytest.raises(ValidationError) as exc:
            AnomalyResult(
                is_anomaly=False, severity="high", confidence=0.9,
                reason="Some reason", rule_triggered="none",
            )
        assert "severity must be null" in str(exc.value)

    def test_severity_null_when_anomaly_rejected(self):
        with pytest.raises(ValidationError) as exc:
            AnomalyResult(
                is_anomaly=True, severity=None, confidence=0.9,
                reason="Some reason", rule_triggered="velocity",
            )
        assert "severity must be set" in str(exc.value)

    def test_confidence_above_1_rejected(self):
        with pytest.raises(ValidationError):
            AnomalyResult(
                is_anomaly=False, severity=None, confidence=1.1,
                reason="Some reason", rule_triggered="none",
            )

    def test_confidence_below_0_rejected(self):
        with pytest.raises(ValidationError):
            AnomalyResult(
                is_anomaly=False, severity=None, confidence=-0.1,
                reason="Some reason", rule_triggered="none",
            )

    def test_reason_too_short_rejected(self):
        with pytest.raises(ValidationError):
            AnomalyResult(
                is_anomaly=False, severity=None, confidence=0.8,
                reason="short", rule_triggered="none",
            )

    def test_is_high_risk_true_for_critical(self):
        r = AnomalyResult(
            is_anomaly=True, severity="critical", confidence=0.95,
            reason="Paris to Tokyo in 45 minutes — geo-impossible",
            rule_triggered="geo_impossible",
        )
        assert r.is_high_risk is True

    def test_is_high_risk_false_for_medium(self):
        r = AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.80,
            reason="Crypto transaction on retail account",
            rule_triggered="high_risk_category",
        )
        assert r.is_high_risk is False


class TestClassificationMetrics:

    def _make_metrics(self, tp, tn, fp, fn, sector="fintech", version="v1.1"):
        return ClassificationMetrics(
            total=tp + tn + fp + fn,
            true_positives=tp, true_negatives=tn,
            false_positives=fp, false_negatives=fn,
            prompt_version=version, sector=sector,
        )

    def test_perfect_classifier(self):
        m = self._make_metrics(tp=40, tn=10, fp=0, fn=0)
        assert m.precision == 1.0
        assert m.recall == 1.0
        assert m.false_positive_rate == 0.0
        assert m.passes_quality_gate()

    def test_high_fp_rate_fails_gate(self):
        m = self._make_metrics(tp=40, tn=5, fp=5, fn=0)
        assert m.false_positive_rate == pytest.approx(0.5)
        assert not m.passes_quality_gate()

    def test_low_recall_fails_gate(self):
        m = self._make_metrics(tp=20, tn=10, fp=0, fn=20)
        assert m.recall == pytest.approx(0.5)
        assert not m.passes_quality_gate()

    def test_f1_score_harmonic_mean(self):
        m = self._make_metrics(tp=8, tn=10, fp=2, fn=2)
        expected_p = 8 / 10
        expected_r = 8 / 10
        expected_f1 = 2 * expected_p * expected_r / (expected_p + expected_r)
        assert m.f1_score == pytest.approx(expected_f1)

    def test_summary_contains_sector_and_verdict(self):
        m = self._make_metrics(tp=40, tn=10, fp=0, fn=0)
        summary = m.summary()
        assert "FINTECH" in summary
        assert "PASS" in summary

    def test_zero_division_safe_precision(self):
        m = self._make_metrics(tp=0, tn=10, fp=0, fn=5)
        assert m.precision == 0.0

    def test_zero_division_safe_recall(self):
        m = self._make_metrics(tp=0, tn=10, fp=2, fn=0)
        assert m.recall == 0.0
