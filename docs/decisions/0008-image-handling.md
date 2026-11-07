# 0008. Image handling: describe for retrieval, send the image for answering

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
Figures raise two separate problems:
1. **Finding the right figure (retrieval).** "How far is the takeoff roll at 30°C?" must land on the takeoff-distance chart.
2. **Reading it (answering).** Something has to read the value at 30°C off the chart.

A description written at indexing time can solve the first problem but not the second, because nobody knew at indexing time which value would be asked for.

The handbook also mixes informational figures with decorative photos. Even stock photos get "Figure X-Y" numbers, so a figure number doesn't tell them apart.

## Options considered
**Finding figures**
- **A. Caption, then embed.** A vision model describes each figure once. The description is embedded as text and is also visible to full-text search. Readable and easy to debug, and it works with any text embedder.
- **B. Embed the image directly** with a multimodal embedding model. No captioning cost, but matching text queries to images is weaker on technical diagrams, full-text search can't see the figure, and few models exist.
- **C. Embed page screenshots** (ColPali family). Strong on visually dense pages, but it stores many vectors per page, makes cropping figures for display hard, and probably isn't available through OpenRouter.

**Reading figures**
- **Description only.** Cheaper, but it can't answer value-reading questions unless the description happened to include that value.
- **Send the image** to a vision-capable generation model.

**Sorting figures**
- **Rules only** (size, repetition, nearby text). Free, but can't tell a stock photo from a diagram of the same size.
- **Describe everything.** Costs more and adds noise.
- **Rules first, then a vision call** that returns `informational: true/false` alongside the description.

**Failures**
- **Fail loudly.** Nothing is silently skipped, but one bad image blocks a 500-page run.
- **Skip silently.** Gaps in coverage go unnoticed.
- **Degrade and report.**

## Decision
- **A** for retrieval: a vision-model description, embedded as text.
- When a figure chunk is retrieved, **send the actual image** to the generation model.
- **Free rules** drop tiny and repeated images such as logos. The **same vision call** that writes the description also returns `informational`. Decorative images keep only their printed caption, so no description is paid for.
- Failures **degrade and are reported.** The item keeps a caption-only chunk, is recorded in `ingest_failures`, and can be re-run. Each ingest produces a report with counts.

## Why
Splitting "find" from "read" lets each step use the cheapest tool that works. Text descriptions keep retrieval in one searchable space and are easy to inspect.

Option B was originally planned as an eval comparison. The strict privacy rule in 0009 rules it out: the only zero-retention multimodal embedders are Gemini Embedding 2, whose endpoint keeps inputs for abuse checks, and Amazon Titan Image v1, which is old and limited to 128 tokens. Instead, the multimodal comparison becomes **answering with the image vs answering from the description only**. It's fully private and tests the question that matters: does looking at the figure help?

## Consequences
- Indexing makes one vision call per non-decorative figure (a few hundred in total; cost is well under $1).
- Figure PNGs are stored (0010) and served for display (0005).
- Revisit option B if a zero-retention multimodal embedder becomes available.
