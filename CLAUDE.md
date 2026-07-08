# CLAUDE.md — Anomaly Sentinel

> AI-assisted anomaly detection QA platform (Fintech / Medtech transaction & telemetry data).
> Portfolio project P1 of a 6-project AI Test Engineering portfolio.

## Project State — READ FIRST

- **Status: ✅ COMPLETE and validated in real conditions.** 182/182 tests passing locally (Windows, Python 3.14).
- This project is in **maintenance mode**. Default posture: do NOT refactor, restructure, or "improve" anything unless explicitly asked.
- Allowed without asking: answering questions about the code, explaining design decisions.
- Requires an explicit request: any code change, dependency bump, file move, or rewrite.
- If a change is requested, make the **smallest targeted fix** that solves the problem. No broad rewrites, ever.

## Environment

- OS: Windows 11, shell: PowerShell
- Python 3.14, virtualenv in `.venv`
- Run tests with: `python -m pytest` — **NEVER** bare `pytest`
- Activate venv: `.\.venv\Scripts\Activate.ps1`
- CI: GitHub Actions (free tier, repo currently private under `BazanJeremy`)

## Architecture Principles (non-negotiable, portfolio-wide)

1. **Deterministic fallback on every AI component.** The full test suite and CI must run green with zero API keys. LLM calls are an enhancement layer, never a dependency.
2. **Pydantic v2** for all data models and validation.
3. **ADRs are first-class deliverables.** They live in `docs/adr/`. Never modify an existing ADR retroactively — supersede it with a new one.
4. **Bugs found by tests are portfolio evidence.** If a test catches a real defect, document it (what the test caught, why manual review missed it) before fixing it.

## Conventions

- Codebase, comments, README, ADRs: **professional English** (international market).
- Conversation with the user: French.
- Commits: small, atomic, imperative English messages (`fix: …`, `test: …`, `docs: …`).
- Free/open-source tools only. If suggesting a tool, it must have a usable free tier.
- Report exact errors, fix precisely. The user runs everything locally and pastes real output.

## Domain Context

- Simulated business problem: detecting anomalous patterns in financial transactions and medical-device telemetry streams.
- Target sectors for interview framing: **Banking/Fintech** (fraud signals, PSD2 context) and **Health/Medtech** (device telemetry drift, patient-safety framing).
- Interview narrative: shift-left anomaly detection as a QA capability, not a data-science project.

## What NOT to Do

- Do not add new dependencies to a completed project.
- Do not touch CI workflows unless they are failing.
- Do not regenerate the README — it is final and senior-reviewed.
- Do not scan `data/`, `.venv/`, or generated report folders unless explicitly needed (token waste).
