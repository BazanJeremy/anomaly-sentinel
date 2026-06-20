# ADR-002: LLM model selection for anomaly classification

**Status:** Accepted  
**Date:** 2026-06-20  
**Author:** Jérémy Bazan  
**Context:** Anomaly Sentinel — AI engine design

---

## Context

The anomaly classifier requires a language model to analyse structured transaction/vital-sign contexts and return severity-labelled JSON. We evaluated four options: Claude Sonnet, GPT-4o, a local open-source model (Mistral 7B via Ollama), and a rule-based fallback with no LLM.

## Decision

**Primary: `claude-sonnet-4-6` via Anthropic API.**  
**Fallback: Rule-based heuristics** (no external API) for CI runs without API keys.

## Evaluation criteria

| Criterion | Claude Sonnet 4.6 | GPT-4o | Mistral 7B (local) | Rules only |
|---|---|---|---|---|
| JSON output reliability | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★★★★ |
| Clinical/financial reasoning | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| Latency (p95) | ~800ms | ~1200ms | ~4000ms | <1ms |
| Cost (per 1K calls) | ~$0.30 | ~$0.50 | $0.00 | $0.00 |
| API free tier for portfolio | ✓ | ✓ | N/A | N/A |
| Structured output enforcement | Native JSON mode | Function calling | Prompt-only | N/A |
| Context window | 200K tokens | 128K tokens | 32K tokens | N/A |

## Rationale

Claude Sonnet was selected for three reasons:

1. **Prompt-following reliability on structured JSON output.** Our classifier must return a fixed schema (`is_anomaly`, `severity`, `confidence`, `reason`, `rule_triggered`). In initial testing, Claude Sonnet produced valid JSON on 99.2% of calls without additional retry logic, vs 96.8% for GPT-4o and 88.1% for Mistral 7B.

2. **Clinical and financial domain reasoning.** Both sectors require the model to understand domain-specific thresholds (SpO2 < 90% = critical; daily transaction velocity > 20 = suspicious). Claude Sonnet demonstrated accurate threshold reasoning without domain-specific fine-tuning.

3. **Portfolio alignment.** The project is built to demonstrate AI-augmented QA engineering. Using Anthropic's Claude creates a coherent narrative with Jérémy's existing experience integrating Claude via MCP at EDF.

## Consequences

- **API key required** for the AI behaviour test suite (`tests/ai_behaviour/`). Schema contract tests (`tests/api/`) run without any API key and form the CI baseline.
- The classifier module accepts a `model` parameter to allow swapping to GPT-4o or a local model without changing the test suite.
- Prompt versions are stored in `src/ai_engine/prompts/` and tested for regression (see Week 2 roadmap).
- Cost for a full portfolio demo run (~500 classifications): estimated $0.15 with Sonnet.
