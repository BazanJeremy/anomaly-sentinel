# ADR-001: Dual-sector architecture with shared core pipeline

**Status:** Accepted  
**Date:** 2026-06-20  
**Author:** Jérémy Bazan  
**Context:** Anomaly Sentinel portfolio project

---

## Context

The project must demonstrate QA engineering credibility across two high-stakes regulated sectors: Fintech (banking, payments) and Medtech (patient monitoring, clinical devices). A naive approach would create two separate, independent codebases — one per sector. This decision record explains why we chose a shared-core, sector-adapter architecture instead.

## Decision

We implement a **single shared pipeline** with sector-specific adapters at the data layer:

```
Shared core:
  - AI anomaly classifier interface
  - Pydantic schema validation layer
  - Test harness (Pytest fixtures, markers, conftest)
  - CI/CD pipeline (matrix strategy)
  - Reporting (Allure, audit logs)

Sector adapters:
  - src/simulators/fintech/  — Transaction events, fraud patterns
  - src/simulators/medtech/  — Vital signs events, clinical anomalies
  - src/schemas/transaction.py  — Fintech contracts
  - src/schemas/vital_signs.py  — Medtech contracts
```

Each adapter exposes the same interface (`generate_<type>_scenario`, `SCENARIO_LABELS`, `to_classifier_context()`) so the AI engine and test layer consume both identically.

## Rationale

**Alternative A: Two separate repos**  
- Pro: complete isolation, sector teams can diverge freely  
- Con: duplicates the entire test infrastructure; any fix to the AI classifier must be applied twice; CI config is duplicated; demonstrates less architectural thinking

**Alternative B: Single monorepo, single sector**  
- Reduces portfolio credibility — most senior QA roles in regulated industries require cross-domain adaptability  
- A recruiter in Fintech and a recruiter in Medtech would need to see different READMEs

**Chosen: Shared core, sector adapters**  
- Demonstrates understanding of the Open/Closed principle applied to testing infrastructure  
- The CI matrix (`sector: [fintech, medtech]`) makes both sectors visible in every build  
- The `to_classifier_context()` interface isolates the AI engine from schema details — same LLM prompt strategy works for transactions and vital signs  
- Sector-specific README sections (see README.md) let us pitch the same codebase differently per job application

## Consequences

- **Positive:** Any improvement to the AI classifier benefits both sectors immediately. Test helpers are reusable. One CI pipeline covers both.  
- **Positive:** Demonstrates systems thinking — a hiring manager at a bank can see how the architecture would extend to a third sector (e.g. insurance) without restructuring.  
- **Negative:** Shared schemas means both sectors must agree on the `to_classifier_context()` contract. Changes require updating both adapters.  
- **Mitigated by:** `test_fintech_schema.py::test_to_classifier_context_*` and equivalent Medtech tests act as regression guards on the interface contract.
