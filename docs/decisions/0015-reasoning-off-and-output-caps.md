# 0015. Hidden reasoning off for figure descriptions and answers

- **Status:** Accepted
- **Date:** 2026-11-09

## Context
The first real ingest (`reports/ingest/20261109T162956Z-ingest.md`) described 496 FAA figures with Claude Haiku 5.5, capped at 700 output tokens. **139 of them (28%) degraded to caption-only.** The losses were concentrated in the dense charts and tables that figure questions depend on: chapter 11's performance charts, chapter 13's weather charts and chapter 10's weight-and-balance graphs.

A probe of four failed figures showed what happened. Every reply ended with `finish_reason: length`. Haiku 5.5 reasons silently by default, and its reasoning tokens are billed as output and count against `max_tokens`. One reply used 1,961 output tokens to produce about 430 tokens of visible JSON. The 20 or so "empty" replies had spent all 700 tokens reasoning before writing a word. `/ask` answers were capped at 600 tokens and use the same model, so they were exposed to the same failure.

OpenRouter exposes one switch for every model that supports it: `reasoning: {enabled: true|false}`. All three generators in 0009 (Haiku, Gemma, Qwen) list `reasoning` as supported.

The same four figures, each re-run with a 3,000-token cap:

| Reasoning | Avg latency | Avg cost | Complete JSON |
|---|---|---|---|
| default (on) | 8.7 s | $0.00094 | 4/4 |
| low effort | 6.5 s | $0.00060 | 4/4 |
| off | 4.5 s | $0.00046 | 4/4 |

Side by side, the density-altitude chart description with reasoning off listed every axis, scale, pressure-altitude line and the standard-temperature line, and explained how to read the chart. It was as complete as the description with reasoning on.

## Options considered
- **Keep default reasoning, raise the caps.** No change to model behaviour, but about 2× the cost and latency on every call, including the live demo's `/ask`.
- **Reasoning off for figures only.** Takes the measured win for indexing, and keeps reasoning for answers on the theory that chart-reading questions benefit from it. That theory is unmeasured, and every live question pays the latency.
- **Reasoning off for both (chosen).** It's cheapest and fastest. Whether answers suffer is a question for the eval, not a guess.

## Decision
- **Hidden reasoning is off by default** for figure descriptions and for `/ask` answers. It's controlled per role by two settings, `VISION_REASONING` and `GENERATION_REASONING`. The judge is unchanged: it keeps its model's default reasoning (0014).
- **Output caps go up as a safety margin:** 700 → 3,000 for figure descriptions, and 600 → 1,200 for answers (`MAX_ANSWER_TOKENS`). With reasoning off, the densest figure measured about 950 tokens. Caps remain cost guards: at most about $0.0015 per figure and $0.0006 per answer on Haiku 5.5.
- **Truncation is detected, not inferred.** The client records OpenRouter's `finish_reason`. A figure reply cut off at the cap fails with "hit the max_tokens cap" rather than "no valid JSON", so the next problem of this kind is diagnosed from the report alone.
- **Eval comparison added to 0011's list:** generator reasoning on vs off (`run_eval.py --reasoning`), with the setting recorded in each report.

## Why
The figure description's job is to make the figure findable. The measurement showed reasoning adds cost and latency without adding content for that job. For answers, the latency matters to the live demo, and the eval will show whether quality suffers. Raising the caps alone would have fixed the symptom but kept paying for hidden work.

## Consequences
- The 139 degraded figures were re-described with `ingest_corpus.py --retry-failures`: 136 resolved. **3 stay caption-only:** text-heavy chapter 2 checklist graphics, where the provider (Amazon Bedrock) ends the reply with `finish_reason: "error"` at about 715 tokens every time. That is an upstream fault, not a cap, and the describer now reports it by name.
- **Haiku 5.5 does not list `temperature` as supported,** so, as with the judge, outputs may vary slightly between runs.
- **The four-figure probe is small.** If the eval shows weak figure retrieval, re-describing with reasoning on is a cheap experiment: one setting, about $0.47 for all figures.
- **Revisit** if the eval's reasoning-on run answers clearly better, or if a model's default reasoning behaviour changes.
