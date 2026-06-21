"""
Classifier performance evaluator.

Computes precision, recall, F1, false positive rate, and per-scenario
accuracy against a labeled dataset. Used by:
  - tests/ai_behaviour/ for assertions
  - reports/ generation (Week 3)
  - ADR-002 model comparison table

This module is intentionally side-effect free — it takes results and
labels as inputs, returns metrics as a dataclass. Easy to test, easy
to pipe into Allure or a Markdown report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from src.ai_engine.models import AnomalyResult


@dataclass
class ClassifierMetrics:
    """
    Standard binary classification metrics for the anomaly detector.

    Attributes mirror what a QA lead would present to a risk committee:
    precision (how many alerts are real), recall (how many real events
    were caught), and false_positive_rate (operational cost of false alerts).
    """

    total: int = 0
    true_positives: int = 0
    true_negatives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    # Per-scenario breakdown (scenario_name -> {tp, fp, fn, tn})
    per_scenario: dict[str, dict] = field(default_factory=dict)

    @property
    def precision(self) -> float:
        """Of all anomalies flagged, what fraction were real?"""
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        """Of all real anomalies, what fraction did we catch?"""
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1_score(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_positive_rate(self) -> float:
        """Of all clean events, what fraction were incorrectly flagged?"""
        denom = self.false_positives + self.true_negatives
        return self.false_positives / denom if denom else 0.0

    @property
    def accuracy(self) -> float:
        return (self.true_positives + self.true_negatives) / self.total if self.total else 0.0

    def summary(self) -> str:
        return (
            f"Accuracy: {self.accuracy:.1%} | "
            f"Precision: {self.precision:.1%} | "
            f"Recall: {self.recall:.1%} | "
            f"F1: {self.f1_score:.1%} | "
            f"FP rate: {self.false_positive_rate:.1%}"
        )

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "true_positives": self.true_positives,
            "true_negatives": self.true_negatives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
        }


def compute_metrics(
    results: Sequence[AnomalyResult],
    labels: Sequence[dict],
    scenario_names: Sequence[str] | None = None,
) -> ClassifierMetrics:
    """
    Compute classification metrics from a batch of results and ground-truth labels.

    Args:
        results: List of AnomalyResult from the classifier.
        labels: List of dicts with "is_anomaly" (bool) and optionally "severity".
                Must match results in length and order.
        scenario_names: Optional list of scenario names for per-scenario breakdown.

    Returns:
        ClassifierMetrics with all computed values.
    """
    if len(results) != len(labels):
        raise ValueError(
            f"results ({len(results)}) and labels ({len(labels)}) must have the same length"
        )

    metrics = ClassifierMetrics(total=len(results))

    for i, (result, label) in enumerate(zip(results, labels)):
        predicted_anomaly = result.is_anomaly
        actual_anomaly = label["is_anomaly"]
        scenario = scenario_names[i] if scenario_names else f"sample_{i}"

        if scenario not in metrics.per_scenario:
            metrics.per_scenario[scenario] = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}

        if predicted_anomaly and actual_anomaly:
            metrics.true_positives += 1
            metrics.per_scenario[scenario]["tp"] += 1
        elif not predicted_anomaly and not actual_anomaly:
            metrics.true_negatives += 1
            metrics.per_scenario[scenario]["tn"] += 1
        elif predicted_anomaly and not actual_anomaly:
            metrics.false_positives += 1
            metrics.per_scenario[scenario]["fp"] += 1
        else:
            metrics.false_negatives += 1
            metrics.per_scenario[scenario]["fn"] += 1

    return metrics


def compare_classifiers(
    llm_metrics: ClassifierMetrics,
    fallback_metrics: ClassifierMetrics,
) -> dict:
    """
    Generate a comparison report showing LLM uplift over rule-based baseline.

    This is the key output for ADR-002 and the README metrics table.
    A negative delta on FP rate is desirable (fewer false alarms with LLM).
    """
    return {
        "metric": ["Accuracy", "Precision", "Recall", "F1", "FP Rate"],
        "llm": [
            f"{llm_metrics.accuracy:.1%}",
            f"{llm_metrics.precision:.1%}",
            f"{llm_metrics.recall:.1%}",
            f"{llm_metrics.f1_score:.1%}",
            f"{llm_metrics.false_positive_rate:.1%}",
        ],
        "fallback": [
            f"{fallback_metrics.accuracy:.1%}",
            f"{fallback_metrics.precision:.1%}",
            f"{fallback_metrics.recall:.1%}",
            f"{fallback_metrics.f1_score:.1%}",
            f"{fallback_metrics.false_positive_rate:.1%}",
        ],
        "delta": [
            f"{(llm_metrics.accuracy - fallback_metrics.accuracy):+.1%}",
            f"{(llm_metrics.precision - fallback_metrics.precision):+.1%}",
            f"{(llm_metrics.recall - fallback_metrics.recall):+.1%}",
            f"{(llm_metrics.f1_score - fallback_metrics.f1_score):+.1%}",
            f"{(llm_metrics.false_positive_rate - fallback_metrics.false_positive_rate):+.1%}",
        ],
    }
