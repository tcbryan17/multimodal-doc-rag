# 0007. Chunking: structure-aware, page-spanning, with deterministic context headers

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
Each chunk becomes one vector, and it's also the unit of citation.
- **Too big** (a whole chapter): the vector blurs many topics together, and the LLM reads irrelevant text.
- **Too small** (one sentence): "It increased 12% year over year" loses what *it* refers to.

The v1 question types (0005) add their own needs:
- fact lookup needs tables to stay whole, with their header rows
- concept explanations need enough surrounding context
- figure answers need figures to be items in their own right

## Options considered
**Where to split**
- **Fixed-size windows with overlap.** Simple, but they cut through tables and sentences.
- **Semantic chunking** (split where embedding similarity drops). Adaptive, but opaque, and costs extra embedding calls.
- **Structure-aware.** Split on section headers first, then by size. Tables and figures are their own chunks.

**Page breaks** (in a printed 10-K they often fall mid-paragraph)
- **Never cross a page.** Exact single-page citations, but print layout creates half-paragraphs.
- **Allow crossing, and record the range.** Paragraphs stay whole. Citations read "pp. 41–42".

**Context header** (prepended to each chunk before embedding)
- **Deterministic:** `Apple 10-K FY2025 › Item 7 MD&A › Liquidity`, built from parsed headings. Free and instant.
- **LLM-written** (Anthropic's "contextual retrieval"): a model writes one or two sentences per chunk. Measurably better on some datasets, but costs one model call per chunk at indexing time.

**Chunk size**
- **Fix a number now.** Simple, but there's no evidence for it.
- **Make it a setting and let the eval decide.**

## Decision
- **Structure-aware splitting.** Tables are one chunk where possible; a table split by rows repeats its header row. Each figure is one chunk.
- **Chunks may span a page break.** They store the start and end page (index and label).
- **Deterministic context header** first. The LLM-written header is an eval comparison later.
- **Size is a setting**, default about 500 tokens. The eval compares 256, 512 and 1024 and keeps the winner. Token counts use a chars/4 approximation.

## Why
Natural boundaries keep each chunk about one thing, which makes overlap mostly unnecessary. Page ranges keep retrieval quality without making citations vague. The deterministic header is one of the cheapest, most effective improvements available, and running it against the LLM-written version shows whether the extra cost pays off. Choosing the size from eval results means we can defend the number.

## Consequences
- The citation contract gains `page_end` (0005).
- Citation accuracy and recall@5 count a hit when the gold page falls within a chunk's page range (0011).
- The chunker needs the parser's section paths and element kinds (0006).
