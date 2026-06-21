"""
AI classifier response models.

Defines the structured output contract for the anomaly classifier.
Using Pydantic here means the classifier output is validated with the
same rigour as the input data — the AI's JSON is never trusted blindly.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FintechRule(str, Enum):
    VELOCITY = "velocity"
    GEO_IMPOSSIBLE = "geo_impossible"
    DORMANT_ACCOUNT = "dormant_account"
    CARD_TESTING = "card_testing"
    HIGH_RISK_CATEGORY = "high_risk_category"
    NONE = "none"


class MedtechRule(str, Enum):
    SPO2_DESATURATION = "spo2_desaturation"
    HYPERTENSIVE_CRISIS = "hypertensive_crisis"
    BRADYCARDIA = "bradycardia"
    HYPOGLYCAEMIA = "hypoglycaemia"
    SENSOR_FAULT = "sensor_fault"
    NONE = "none"


class AnomalyResult(BaseModel):
    """
    Structured output from the AI anomaly classifier.

    Validated on receipt — a malformed LLM response raises ValidationError
    before it can propagate into the test metrics or alert pipeline.
    """

    is_anomaly: bool
    severity: Optional[Severity] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., min_length=10, max_length=500)
    rule_triggered: str  # Accepts both FintechRule and MedtechRule values

    @model_validator(mode="after")
    def severity_null_iff_not_anomaly(self) -> "AnomalyResult":
        if not self.is_anomaly and self.severity is not None:
            raise ValueError(
                "severity must be null when is_anomaly is False"
            )
        if self.is_anomaly and self.severity is None:
            raise ValueError(
                "severity must be set when is_anomaly is True"
            )
        return self

    @property
    def is_high_risk(self) -> bool:
        return self.severity in (Severity.HIGH, Severity.CRITICAL)


class ClassificationMetrics(BaseModel):
    """
    Aggregate precision/recall/FP metrics for a batch evaluation run.
    Used by the quality gate in CI.
    """

    total: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    prompt_version: str
    sector: str

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1_score(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def false_positive_rate(self) -> float:
        denom = self.false_positives + self.true_negatives
        return self.false_positives / denom if denom > 0 else 0.0

    def passes_quality_gate(
        self,
        min_precision: float = 0.85,
        min_recall: float = 0.85,
        max_fp_rate: float = 0.05,
    ) -> bool:
        return (
            self.precision >= min_precision
            and self.recall >= min_recall
            and self.false_positive_rate <= max_fp_rate
        )

    def summary(self) -> str:
        return (
            f"[{self.sector.upper()} | prompt={self.prompt_version}] "
            f"P={self.precision:.1%} R={self.recall:.1%} "
            f"F1={self.f1_score:.1%} FP_rate={self.false_positive_rate:.1%} "
            f"({'PASS' if self.passes_quality_gate() else 'FAIL'})"
        )
