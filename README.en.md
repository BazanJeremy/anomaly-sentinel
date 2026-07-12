# Anomaly Sentinel

**AI-augmented test framework for anomaly detection systems in regulated industries — Medtech & Fintech**

[![CI](https://github.com/BazanJeremy/anomaly-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/BazanJeremy/anomaly-sentinel/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-182%20passing-brightgreen?logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue?logo=python)](requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

> 🇫🇷 [Version française](README.md)

## What this framework demonstrates

Anomaly Sentinel is an AI-augmented **test framework** that addresses a real QA engineering challenge: how do you test an AI system that is itself responsible for detecting anomalies in critical data streams?

The framework covers two regulated sectors under a shared core pipeline:

- **Medtech** — patient vital signs monitoring (SpO₂ desaturation, hypertensive crisis, bradycardia, hypoglycaemia, sensor drift) with IEC 62304 traceability context
- **Fintech** — transaction fraud detection (velocity bursts, geo-impossible travel, dormant account spikes, card testing, high-risk category mismatches) with PSD2/AML compliance context

The AI classifier (Claude `claude-sonnet-4-6`) is treated as a **system under test** — not a tool that generates tests. Every prediction is validated against a Pydantic schema, measured for precision/recall/FP rate, and gated by a CI quality threshold.

---

## Architecture

```
anomaly-sentinel/
├── src/
│   ├── schemas/                  # Pydantic v2 data contracts
│   │   ├── transaction.py        # Fintech — Transaction, GeoLocation, DeviceInfo
│   │   └── vital_signs.py        # Medtech — VitalSigns, DeviceSensorInfo
│   ├── simulators/
│   │   ├── fintech/generator.py  # 6 labeled fraud scenarios + SCENARIO_LABELS
│   │   └── medtech/generator.py  # 6 labeled clinical scenarios + SCENARIO_LABELS
│   ├── ai_engine/
│   │   ├── classifier.py         # Claude API + rule-based fallback (dual-mode)
│   │   ├── models.py             # AnomalyResult, ClassificationMetrics (Pydantic)
│   │   └── prompts/              # Versioned prompt files (fintech_v1.0/v1.1, medtech_v1.0)
│   └── dashboard/
│       ├── app.py                # Flask REST API + live dashboard
│       └── templates/index.html  # Single-page UI (classify + batch + scenario registry)
├── tests/
│   ├── api/                      # Schema contract tests (Pytest)
│   ├── ai_behaviour/             # AI classifier behaviour tests (precision/recall/FP)
│   └── e2e/                      # REST API + Playwright UI tests
├── docs/
│   ├── ADR-001-dual-sector-architecture.md
│   └── ADR-002-ai-model-choice.md
└── .github/workflows/ci.yml      # 3-job matrix CI (schema / AI / E2E) × Python 3.11|3.12
```

### Dual-mode design

The classifier runs in two modes, selected automatically:

| Mode | When | Use case |
|---|---|---|
| **LLM mode** | `ANTHROPIC_API_KEY` is set | Local dev, protected CI jobs, demo |
| **Fallback mode** | No API key present | CI without secrets, offline testing |

The rule-based fallback is not a stub — it is a **specification** of the LLM's expected behaviour. If the LLM diverges from the rules, a test fails and triggers a prompt revision.

---

## Test strategy

### Layer 1 — Schema contract tests (`tests/api/`) — 59 tests

Validates Pydantic v2 models enforce business-level constraints, not just types.

Examples:
- `diastolic_bp_mmhg` must always be strictly less than `systolic_bp_mmhg` (IEC 62304 ref: SR-VITALS-002)
- SpO₂ drop rate > 10%/min is physiologically impossible — rejected as sensor fault
- `daily_total_amount` must include the current transaction — cross-field validator
- `to_classifier_context()` strips PII fields before LLM injection

```bash
python -m pytest tests/api/ -v -m fintech   # Fintech contracts only
python -m pytest tests/api/ -v -m medtech   # Medtech contracts only
```

### Layer 2 — AI behaviour tests (`tests/ai_behaviour/`) — 55 tests

Treats the AI classifier as a black-box component with measurable, observable behaviour.

Six test categories per sector:

| Category | What it checks |
|---|---|
| Single-scenario correctness | Each fraud/clinical pattern detected with correct severity |
| False positive rate | ≤ 5% FP on a corpus of 50 normal samples (quality gate) |
| Batch precision/recall | ≥ 85% precision, ≥ 85% recall across all scenarios |
| Prompt regression | `v1.1` must not degrade accuracy vs `v1.0` on same dataset |
| Output schema validation | LLM response always parses to valid `AnomalyResult` |
| Confidence calibration | Predictions with confidence ≥ 0.85 must be correct |

Medtech-specific:
- **Zero missed critical alerts** — `spo2_desaturation` must be detected on 10/10 runs (clinical safety requirement)
- **Sensor fault ≠ clinical emergency** — `sensor_drift` must not trigger `severity=critical`

```bash
python -m pytest tests/ai_behaviour/ -v                        # All AI behaviour tests (fallback mode)
ANTHROPIC_API_KEY=sk-... python -m pytest tests/ai_behaviour/  # LLM mode
```

### Layer 3 — E2E tests (`tests/e2e/`) — 68 tests

**API tests (49):** full REST contract coverage — happy path, error codes (400/404/405), parametrized scenario matrix, quality gate via `/api/batch`.

**Playwright UI tests (19):** headless Chromium against a live Flask server spun up within the pytest session.

- Page load, title, header badge (LLM vs Fallback mode)
- Scenario dropdown populated from API, repopulated on sector switch
- Classify button → JSON result visible with all required keys
- Batch run → metrics grid with 6 tiles → quality gate tile shows PASS/FAIL

```bash
python -m pytest tests/e2e/test_api_endpoints.py -v   # API contract tests
python -m pytest tests/e2e/test_dashboard_ui.py -v    # Playwright UI tests
```

### Quality gates

| Gate | Threshold | Enforced by |
|---|---|---|
| Schema validation | 100% pass | `tests/api/` |
| FP rate | ≤ 5% | `test_fp_rate_under_5pct` |
| Precision | ≥ 85% | `test_batch_precision_above_threshold` |
| Recall | ≥ 85% | `test_batch_recall_above_threshold` |
| Critical alert recall | 100% | `test_spo2_desaturation_never_missed` |
| CI merge block | All jobs green | `.github/workflows/ci.yml` quality-gate job |

---

## Key design decisions

See [`docs/ADR-001`](./docs/ADR-001-dual-sector-architecture.md) and [`docs/ADR-002`](./docs/ADR-002-ai-model-choice.md) for full rationale.

**Why a shared core + sector adapters?**
Both sectors expose the same interface (`generate_*_scenario`, `SCENARIO_LABELS`, `to_classifier_context()`). The AI engine and test layer consume both identically. A third sector (e.g. insurance, energy) can be added without touching the classifier or the CI pipeline.

**Why test the LLM output with Pydantic?**
External system output — including LLM responses — should be validated as rigorously as any API response. `AnomalyResult` enforces cross-field constraints (e.g. `severity` must be null when `is_anomaly` is false) that JSON Schema alone cannot express.

**Why prompt versioning?**
A prompt file is a configuration artefact. Without versioning and regression tests, a one-line edit can silently degrade classifier accuracy. `fintech_v1.0` → `fintech_v1.1` is tracked in git; `test_prompt_version_passes_quality_gate` runs against both on every push.

**Rule priority ordering in the fallback classifier**
During development, the sensor-fault battery check had to be evaluated *before* the SpO₂ delta rule — otherwise a degraded sensor oscillating between 91% and 99% would trigger a clinical emergency alert instead of a technical fault. This ordering decision is now enforced by `test_sensor_fault_is_anomaly_not_clinical_emergency`.

---

## Running the framework

### Prerequisites

```bash
git clone https://github.com/BazanJeremy/anomaly-sentinel.git
cd anomaly-sentinel
pip install -r requirements.txt
python -m playwright install chromium
```

### Run all tests

```bash
python -m pytest tests/ -v                            # Full suite (182 tests, fallback mode)
ANTHROPIC_API_KEY=sk-... python -m pytest tests/ -v   # Full suite with live Claude API
```

### Run the dashboard

```bash
python -m flask --app src/dashboard/app run --port 5000
# Open http://localhost:5000
```

### Run by layer

```bash
python -m pytest tests/api/           # Schema contracts (no API key needed)
python -m pytest tests/ai_behaviour/  # AI classifier behaviour
python -m pytest tests/e2e/           # REST API + Playwright UI
```

---

## Sector-specific notes

### Medtech / Clinical Monitoring

This framework applies directly to **patient monitoring systems**, **ICU alert pipelines**, and **medical device software** developed under IEC 62304.

Clinical thresholds are sourced from WHO vital signs reference ranges and validated against the schema layer with IEC 62304-style requirement references in test comments:

| Scenario | Clinical event | Severity |
|---|---|---|
| `spo2_desaturation` | SpO₂ < 90% | Critical |
| `hypertensive_crisis` | Systolic BP ≥ 180 mmHg | High |
| `bradycardia_event` | Heart rate < 40 bpm | High |
| `hypoglycaemia_alert` | Glucose < 3.5 mmol/L | Medium |
| `sensor_drift` | Low-battery device, implausible oscillation | Medium |
| `stable_routine` | Baseline — no anomaly | — |

**Safety-critical gate:** zero missed critical alerts (`spo2_desaturation` detected 10/10 runs).

### Fintech / Banking

This framework applies directly to **transaction monitoring**, **AML screening**, and **PSD2 Strong Customer Authentication** anomaly detection.

Fraud patterns implemented are based on real-world typologies documented in FATF guidance and Europol financial crime reports:

| Scenario | Pattern | Expected severity |
|---|---|---|
| `geo_impossible` | Two locations > 1000 km apart in < 60 min | Critical |
| `velocity_burst` | > 15 transactions/day or > 8 in 2 hours | High |
| `card_testing` | Amount < €1.00 on unknown device | High |
| `dormant_account_spike` | 90+ day inactivity → high-value transfer, unknown device | Medium |
| `high_risk_category` | Crypto/gambling on retail account, > €200 | Medium |
| `normal_purchase` | Baseline — no anomaly | — |

**Operational KPIs visible in CI:** FP rate 0% (fallback), batch precision 100%, batch recall 100%.

---

## Bugs found and fixed during development

This framework was built using a **shift-left QA** approach — defects were caught by tests before any manual verification was needed.

| Bug | Layer detected | Root cause | Fix |
|---|---|---|---|
| `device` kwarg passed twice | Schema test | `_base_account()` included `device`, scenarios also passed it explicitly | Removed from base dict; each scenario sets its own device |
| `account_age_days` missing after refactor | Schema test | Field removed from `_base_account()` but not added to 3 scenarios | Added explicitly to each scenario factory |
| `diastolic_bp_mmhg` exceeding schema max (201) | AI behaviour test | `hypertensive_crisis` generator used `systolic - 30` without clamping to schema max of 200 | Clamped: `min(systolic - 30, 200)` |
| Bradycardia classified as `critical` instead of `high` | AI behaviour test | Fallback checked SpO₂ (which can be 88–94% in bradycardia) before heart rate | Tightened generator SpO₂ range to 91–95% (above clinical threshold) |
| Sensor drift classified as `critical` clinical alert | AI behaviour test | Battery check rule evaluated after SpO₂ delta rule — low-battery oscillation triggered wrong rule | Moved battery check before SpO₂ delta in fallback rule priority |

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 / 3.12 |
| Data validation | Pydantic v2 |
| AI classifier | Anthropic Claude `claude-sonnet-4-6` |
| Test data | Faker |
| Testing | Pytest, pytest-playwright |
| Browser automation | Playwright (headless Chromium) |
| Dashboard | Flask 3 |
| CI/CD | GitHub Actions (matrix strategy) |
| Documentation | ADR format (Architecture Decision Records) |

---

## Related projects

These tools share the same principles: **deterministic first, AI where it earns its place — the QA stays the arbiter.** All run locally, no API keys required.

| Project | Focus |
|---|---|
| [EvalForge](https://github.com/BazanJeremy/EvalForge) | LLM evaluation & judge calibration |
| [ReleaseGuard](https://github.com/BazanJeremy/ReleaseGuard) | Explainable GO/NO-GO release gate |
| [FlakySense](https://github.com/BazanJeremy/flakysense) | Statistical flaky-test diagnosis |
| [Anomaly Sentinel](https://github.com/BazanJeremy/anomaly-sentinel) **← this repo** | Testing AI anomaly-detection systems (medtech · fintech) |
| [TestScribe](https://github.com/BazanJeremy/testscribe) | AI-assisted bug report enrichment |
| [SkyGuard](https://github.com/BazanJeremy/skyguard) | Security quality gate for critical avionics systems |

## About

Built by **Jérémy Bazan** — QA Engineer with expertise in regulated-industry testing, AI-augmented QA, and test automation at scale.

- ISTQB Foundation v4 certified
- Experience integrating Claude and GPT via MCP in production QA pipelines at a major energy-sector group
- Fluent in French and English (professional native level)

[LinkedIn](https://www.linkedin.com/in/jeremy-bazan/) · [GitHub](https://github.com/BazanJeremy)
