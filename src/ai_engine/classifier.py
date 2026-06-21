"""
AI anomaly classifier — core engine.

Wraps the Claude API with:
  - Prompt versioning (load from files, swap without code changes)
  - Structured JSON output with Pydantic validation on receipt
  - Retry logic with exponential backoff
  - Rule-based fallback when no API key is available (CI without secrets)
  - Cost tracking per run (tokens in/out)

Design principle: the classifier is ITSELF a system under test.
The test suite in tests/ai_behaviour/ measures its precision, recall,
and FP rate against labeled scenarios — treating the LLM as a black-box
component with observable, measurable behaviour.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Literal, Optional, Union

import anthropic
from pydantic import ValidationError

from src.ai_engine.models import AnomalyResult, ClassificationMetrics
from src.schemas.transaction import Transaction
from src.schemas.vital_signs import VitalSigns

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 512

Sector = Literal["fintech", "medtech"]
PromptVersion = Literal["v1.0", "v1.1"]

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def _load_prompt(sector: Sector, version: PromptVersion) -> str:
    path = PROMPTS_DIR / f"{sector}_{version}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt not found: {path}. "
            f"Available: {list(PROMPTS_DIR.glob('*.txt'))}"
        )
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Rule-based fallback (no API key required)
# ---------------------------------------------------------------------------

def _rule_based_classify_fintech(tx: Transaction) -> AnomalyResult:
    """
    Deterministic heuristic classifier for CI runs without API key.
    Mirrors the logic described in fintech_v1.1.txt.
    Used automatically when ANTHROPIC_API_KEY is not set.
    """
    ctx = tx.to_classifier_context()

    # GEO_IMPOSSIBLE
    if ctx.get("previous_country") and ctx["previous_country"] != ctx["location_country"]:
        minutes = ctx.get("minutes_since_last_tx", 999)
        if minutes < 120:
            return AnomalyResult(
                is_anomaly=True, severity="critical", confidence=0.95,
                reason=f"Transaction in {ctx['location_country']} only {minutes:.0f} min after {ctx['previous_country']}",
                rule_triggered="geo_impossible",
            )

    # VELOCITY
    if ctx["daily_tx_count"] >= 15:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.90,
            reason=f"{ctx['daily_tx_count']} transactions recorded today — velocity threshold exceeded",
            rule_triggered="velocity",
        )

    # DORMANT_ACCOUNT + unknown device
    if (
        not ctx["is_known_device"]
        and ctx.get("minutes_since_last_tx", 0) > 60 * 24 * 89  # >89 days
        and ctx["amount"] > 500
    ):
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.85,
            reason=f"Dormant account spike: €{ctx['amount']:.2f} on unknown device after long inactivity",
            rule_triggered="dormant_account",
        )

    # CARD_TESTING
    if ctx["amount"] < 1.0 and not ctx["is_known_device"]:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.88,
            reason=f"Micro-transaction €{ctx['amount']:.2f} on unknown device — card testing pattern",
            rule_triggered="card_testing",
        )

    # HIGH_RISK_CATEGORY
    if ctx["merchant_category"] in ("crypto", "gambling") and ctx["amount"] > 200:
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.80,
            reason=f"€{ctx['amount']:.2f} to {ctx['merchant_category']} merchant on retail-profile account",
            rule_triggered="high_risk_category",
        )

    return AnomalyResult(
        is_anomaly=False, severity=None, confidence=0.87,
        reason="No fraud heuristics triggered; transaction within normal parameters",
        rule_triggered="none",
    )


def _rule_based_classify_medtech(vs: VitalSigns) -> AnomalyResult:
    """Deterministic fallback for Medtech — mirrors medtech_v1.0.txt thresholds."""
    ctx = vs.to_classifier_context()

    # SENSOR FAULT — check BEFORE spo2 delta rule (low battery invalidates readings)
    if ctx["battery_pct"] <= 20:
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.82,
            reason=f"Device battery at {ctx['battery_pct']}% — sensor readings may be unreliable",
            rule_triggered="sensor_fault",
        )

    # SPO2 DESATURATION
    if ctx.get("spo2") is not None and ctx["spo2"] < 90:
        return AnomalyResult(
            is_anomaly=True, severity="critical", confidence=0.95,
            reason=f"SpO2 {ctx['spo2']}% — below critical threshold of 90%",
            rule_triggered="spo2_desaturation",
        )

    if ctx.get("spo2") is not None and ctx.get("spo2_delta", 0) < -4:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.88,
            reason=f"SpO2 dropping rapidly (delta {ctx['spo2_delta']}%) — escalating desaturation",
            rule_triggered="spo2_desaturation",
        )

    # HYPERTENSIVE CRISIS
    if ctx.get("sbp") is not None and ctx["sbp"] >= 180:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.92,
            reason=f"Systolic BP {ctx['sbp']} mmHg — hypertensive crisis threshold exceeded",
            rule_triggered="hypertensive_crisis",
        )

    # BRADYCARDIA
    if ctx.get("hr_bpm") is not None and ctx["hr_bpm"] < 40:
        return AnomalyResult(
            is_anomaly=True, severity="high", confidence=0.93,
            reason=f"Heart rate {ctx['hr_bpm']} bpm — clinical bradycardia",
            rule_triggered="bradycardia",
        )

    # HYPOGLYCAEMIA
    if ctx.get("glucose") is not None and ctx["glucose"] < 3.5:
        return AnomalyResult(
            is_anomaly=True, severity="medium", confidence=0.90,
            reason=f"Glucose {ctx['glucose']} mmol/L — hypoglycaemia threshold (<3.5)",
            rule_triggered="hypoglycaemia",
        )

    return AnomalyResult(
        is_anomaly=False, severity=None, confidence=0.88,
        reason="All measured vitals within clinical reference ranges",
        rule_triggered="none",
    )


# ---------------------------------------------------------------------------
# LLM classifier
# ---------------------------------------------------------------------------

def _call_claude(system_prompt: str, context: dict, retries: int = 2) -> str:
    """Call Claude API with retry logic. Returns raw response text."""
    client = anthropic.Anthropic()
    context_str = json.dumps(context, indent=2)
    user_message = system_prompt.replace("{context}", context_str)

    for attempt in range(retries + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            if attempt < retries:
                wait = 2 ** attempt
                logger.warning(f"Rate limit hit, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise


def _parse_llm_response(raw: str) -> AnomalyResult:
    """
    Parse and validate LLM JSON output.
    Strips markdown fences if the model wraps output despite instructions.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nRaw: {raw[:200]}")

    try:
        return AnomalyResult(**data)
    except ValidationError as e:
        raise ValueError(f"LLM response failed schema validation: {e}\nData: {data}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_transaction(
    tx: Transaction,
    prompt_version: PromptVersion = "v1.1",
    use_fallback: bool = False,
) -> AnomalyResult:
    """
    Classify a transaction as anomaly or not.

    Args:
        tx: Validated Transaction object (Pydantic schema enforced upstream)
        prompt_version: Which prompt file to load from src/ai_engine/prompts/
        use_fallback: Force rule-based fallback (skips API call)

    Returns:
        AnomalyResult with is_anomaly, severity, confidence, reason, rule_triggered
    """
    if use_fallback or not os.getenv("ANTHROPIC_API_KEY"):
        logger.debug("Using rule-based fallback (no API key or fallback forced)")
        return _rule_based_classify_fintech(tx)

    prompt = _load_prompt("fintech", prompt_version)
    context = tx.to_classifier_context()
    raw = _call_claude(prompt, context)
    return _parse_llm_response(raw)


def classify_vital_signs(
    vs: VitalSigns,
    prompt_version: PromptVersion = "v1.0",
    use_fallback: bool = False,
) -> AnomalyResult:
    """
    Classify a vital signs reading as clinical anomaly or not.
    """
    if use_fallback or not os.getenv("ANTHROPIC_API_KEY"):
        logger.debug("Using rule-based fallback (no API key or fallback forced)")
        return _rule_based_classify_medtech(vs)

    prompt = _load_prompt("medtech", prompt_version)
    context = vs.to_classifier_context()
    raw = _call_claude(prompt, context)
    return _parse_llm_response(raw)


def evaluate_batch(
    dataset: list[tuple[Union[Transaction, VitalSigns], dict]],
    sector: Sector,
    prompt_version: PromptVersion,
    use_fallback: bool = False,
) -> ClassificationMetrics:
    """
    Run the classifier over a labeled dataset and compute precision/recall/FP metrics.

    Args:
        dataset: List of (data_object, label_dict) tuples.
                 label_dict has keys: {"is_anomaly": bool, "severity": str | None}
        sector: "fintech" or "medtech"
        prompt_version: Prompt file to use
        use_fallback: Skip API calls (for CI without API key)

    Returns:
        ClassificationMetrics with precision, recall, FP rate, and quality gate check
    """
    tp = tn = fp = fn = 0

    classify_fn = classify_transaction if sector == "fintech" else classify_vital_signs

    for data_obj, label in dataset:
        result = classify_fn(
            data_obj,
            prompt_version=prompt_version,
            use_fallback=use_fallback,
        )
        expected = label["is_anomaly"]
        predicted = result.is_anomaly

        if expected and predicted:
            tp += 1
        elif not expected and not predicted:
            tn += 1
        elif not expected and predicted:
            fp += 1
        else:
            fn += 1

    return ClassificationMetrics(
        total=len(dataset),
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        prompt_version=prompt_version,
        sector=sector,
    )
