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
| API free tier available | ✓ | ✓ | N/A | N/A |
| Structured output enforcement | Native JSON mode | Function calling | Prompt-only | N/A |
| Context window | 200K tokens | 128K tokens | 32K tokens | N/A |

## Rationale

Claude Sonnet was selected for three reasons:

1. **Prompt-following reliability on structured JSON output.** Our classifier must return a fixed schema (`is_anomaly`, `severity`, `confidence`, `reason`, `rule_triggered`). In initial testing, Claude Sonnet produced valid JSON on 99.2% of calls without additional retry logic, vs 96.8% for GPT-4o and 88.1% for Mistral 7B.

2. **Clinical and financial domain reasoning.** Both sectors require the model to understand domain-specific thresholds (SpO2 < 90% = critical; daily transaction velocity ≥ 15 = suspicious). Claude Sonnet demonstrated accurate threshold reasoning without domain-specific fine-tuning.

3. **Ecosystem alignment.** The framework demonstrates AI-augmented QA engineering and builds on prior production experience integrating Claude via MCP in enterprise QA pipelines.

## Consequences

- **No API key required** to run any test, `tests/ai_behaviour/` included: without a key, the classifier falls back to its rules, and that is what CI runs. A key is only needed to exercise the LLM itself. See the amendment below.
- The model identifier is centralised in a single `MODEL` constant in the classifier module, so it can be swapped for GPT-4o or a local model without changing the test suite.
- Prompt versions are stored in `src/ai_engine/prompts/`. The prompt regression tests only exercise them in LLM mode: on push, without a key, no prompt is read.
- Cost for a full demo run (~500 classifications): estimated $0.15 with Sonnet.

---

## Amendment — 2026-09-22

Re-reading the code while fact-checking a published article showed three points where this
record said more than the repository supports.

- **Velocity threshold.** The rationale cited "daily transaction velocity > 20". The rules in
  `classifier.py` fire at `daily_tx_count >= 15`; the `> 20` and `> 30` thresholds lived in
  `src/ai_engine/fallback.py`, a module nothing imported, now removed. Corrected above.
- **API key and CI.** The consequences said an API key was required for the AI behaviour
  suite. It is not: without a key the classifier uses its rules, and the whole suite runs that
  way in CI. As a result, prompts are never read on push. Both lines are corrected above.
- **Evaluation figures.** The JSON-validity rates (99.2%, 96.8%, 88.1%), the p95 latencies,
  the costs per 1K calls and the statement that Claude Sonnet "demonstrated accurate threshold
  reasoning" are not backed by any script, dataset or run log in this repository. Until such a
  measurement is published, read them as unverified.

The decision itself is what the code implements: Claude Sonnet as the primary model, a
rule-based fallback for runs without a key.
