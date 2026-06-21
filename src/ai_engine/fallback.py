"""
Rule-based fallback classifier.

Used when:
  1. No API key is available (CI without secrets, local dev)
  2. The LLM call fails after retries
  3. The LLM returns unparseable output

These rules encode the same thresholds as the LLM prompts, ensuring
the fallback is a meaningful baseline — not just a stub.

In AI behaviour tests, we assert that the LLM outperforms this baseline.
That comparison is the core value of the AI classifier tests.
"""

from __future__ import annotations

from src.ai_engine.models import AnomalyResult


def classify_transaction_fallback(context: dict) -> AnomalyResult:
    """Rule-based transaction anomaly detection."""

    # GEO_IMPOSSIBLE: previous country known + elapsed < 120 min
    if (
        context.get("previous_country")
        and context.get("minutes_since_last_tx") is not None
        and context["minutes_since_last_tx"] < 120
        and context.get("location_country") != context["previous_country"]
    ):
        # Crude check — any cross-country in <2h is flagged
        return AnomalyResult(
            is_anomaly=True, severity="critical", confidence=0.95,
            reason="Cross-country transaction within 2 hours of previous",
            rule_triggered="geo_impossible", source="fallback",
        )

    # VELOCITY
    if context.get("daily_tx_count", 0) > 30:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.90,
            reason=f"Velocity burst: {context['daily_tx_count']} transactions today",
            rule_triggered="velocity", source="fallback",
        )
    if context.get("daily_tx_count", 0) > 20:
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.75,
            reason=f"Elevated velocity: {context['daily_tx_count']} transactions today",
            rule_triggered="velocity", source="fallback",
        )

    # CARD_TESTING
    if (
        context.get("amount", 999) < 1.00
        and not context.get("is_known_device", True)
    ):
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.85,
            reason="Micro-amount on unknown device — card testing pattern",
            rule_triggered="card_testing", source="fallback",
        )

    # DORMANT
    if (
        context.get("minutes_since_last_tx") is not None
        and context["minutes_since_last_tx"] > 43200  # 30 days
        and context.get("amount", 0) > 1000
    ):
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.80,
            reason="Large transaction after 30+ day dormancy",
            rule_triggered="dormant", source="fallback",
        )

    # HIGH_RISK_CATEGORY
    if (
        context.get("merchant_category") in ("crypto", "gambling")
        and context.get("amount", 0) > 500
    ):
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.70,
            reason=f"High-value {context['merchant_category']} transaction",
            rule_triggered="high_risk_category", source="fallback",
        )

    return AnomalyResult(
        is_anomaly=False, severity=None, confidence=0.85,
        reason="No fraud pattern detected by rule engine",
        rule_triggered="none", source="fallback",
    )


def classify_vitals_fallback(context: dict) -> AnomalyResult:
    """Rule-based vital signs anomaly detection."""

    spo2 = context.get("spo2")
    hr = context.get("hr_bpm")
    sbp = context.get("sbp")
    glucose = context.get("glucose")
    battery = context.get("battery_pct", 100)
    spo2_delta = context.get("spo2_delta")

    # SENSOR_DRIFT: low battery + borderline reading
    if battery < 20 and spo2 is not None and spo2 < 95:
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.70,
            reason=f"Low battery ({battery}%) with abnormal SpO2 — possible sensor drift",
            rule_triggered="sensor_drift", source="fallback",
        )

    # SPO2 CRITICAL
    if spo2 is not None and spo2 < 90:
        return AnomalyResult(
            is_anomaly=True, severity="critical", confidence=0.95,
            reason=f"SpO2 {spo2}% — below hypoxia intervention threshold (90%)",
            rule_triggered="spo2_critical", source="fallback",
        )

    # RAPID DESATURATION
    if spo2_delta is not None and spo2_delta < -5:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.88,
            reason=f"SpO2 dropped {abs(spo2_delta):.1f}% rapidly",
            rule_triggered="rapid_desaturation", source="fallback",
        )

    # SPO2 HIGH (90-94%)
    if spo2 is not None and spo2 < 94:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.80,
            reason=f"SpO2 {spo2}% — supplemental oxygen may be indicated",
            rule_triggered="spo2_high", source="fallback",
        )

    # BRADYCARDIA
    if hr is not None and hr < 40:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.92,
            reason=f"Bradycardia: heart rate {hr} bpm",
            rule_triggered="bradycardia", source="fallback",
        )

    # TACHYCARDIA
    if hr is not None and hr > 150:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.88,
            reason=f"Tachycardia: heart rate {hr} bpm",
            rule_triggered="tachycardia", source="fallback",
        )

    # HYPERTENSION CRISIS
    if sbp is not None and sbp >= 180:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.90,
            reason=f"Hypertensive crisis: systolic BP {sbp} mmHg",
            rule_triggered="hypertension", source="fallback",
        )

    # HYPOGLYCAEMIA
    if glucose is not None and glucose < 2.5:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.93,
            reason=f"Severe hypoglycaemia: glucose {glucose} mmol/L",
            rule_triggered="hypoglycaemia", source="fallback",
        )
    if glucose is not None and glucose < 3.5:
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.85,
            reason=f"Hypoglycaemia: glucose {glucose} mmol/L",
            rule_triggered="hypoglycaemia", source="fallback",
        )

    return AnomalyResult(
        is_anomaly=False, severity=None, confidence=0.80,
        reason="Vitals within acceptable clinical ranges",
        rule_triggered="none", source="fallback",
    )
