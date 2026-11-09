# 0011. Eval methodology

- **Status:** Accepted (amended by [0017](0017-eval-validity.md): the judge sees figure images, binding runs are unfiltered, comparison tooling)
- **Date:** 2026-11-07

## Context
Eval is central to the portfolio story. It's also separate from testing:
- **Tests** check that the code does what it should. They're deterministic, make no network calls, run on every commit, and either pass or fail.
- **Evals** measure how *good* the system is. They make real model calls, cost money, produce scores, and run when something changes.

## Options considered
**Creating the gold set**
- **All hand-written.** The most credible, but slow (about 160 questions).
- **LLM-generated only.** Fast, but questions echo the source wording, which inflates retrieval scores. Hard to defend.
- **LLM drafts, a human verifies every item.**

**Size**
- 30+10 per corpus (differences under about 15 points are noise).
- 60+20 per corpus.
- 100+30 per corpus (a lot of review time).

**Judging correctness and faithfulness**
- **Rules only.** Can't judge explanations.
- **The owner grades everything.** Most trustworthy, but blocks frequent runs.
- **An LLM judge, calibrated against human grades.**

## Decision
- **Gold set:** a model drafts questions from sampled pages, and the owner reviews, edits or rejects **every** item. The owner writes the figure-reading questions personally, because generated questions skew towards ones that are easy to retrieve. Each item records:
  - the question and a reference answer
  - the gold pages (`doc`, page index and label)
  - the type (fact, figure or concept)
  - whether it's answerable
- **Size:** per corpus, **60 dev + 20 held-out** (about 160 in total, with about 10% unanswerable). Choices are tuned on dev only. Held-out results are reported once at the end.
  - **10-K held-out:** a company never used for tuning (Costco; see 0013).
  - **Handbook held-out:** about 3 chapters never used for tuning.
- **Metrics:**
  - recall@5: a gold page falls within a top-5 chunk's page-index range
  - correctness
  - faithfulness: every claim is supported by retrieved passages
  - citation accuracy
  - abstention rate on unanswerable questions
  - cost and latency per question
- **Judging:** a zero-data-retention LLM judge, **from a different model family than the generators it grades** (models tend to favour their own family's answers). Numeric facts are also checked by exact match. The owner hand-grades about 30 answers, and the report states how often the judge agreed.
- **Safety:**
  - unanswerable questions
  - about 15 direct-injection questions (the user tries to override instructions or leak the prompt)
  - indirect injection: a synthetic poisoned document in an **eval-only** index, which must be treated as data, not instructions
- **How it runs:** evals live in `evals/` as a script, outside pytest. Each run has a cost cap and writes a committed JSON + Markdown report.
- **Planned comparisons:**
  - chunk size (256/512/1024)
  - embedder (Qwen3 vs text-embedding-3-small)
  - reranker on vs off
  - the three generators
  - figure image vs description only
  - deterministic vs LLM-written context headers

## Why
Human verification keeps generated questions honest. The held-out split stops us from reporting numbers we tuned on. Measuring the judge against human grades is what makes LLM-judged scores credible, and few portfolio projects do it.

## Consequences
- Building the gold set is substantial owner work, scheduled after real ingestion.
- A full run costs well under $1 at current prices, but it may need OpenRouter's higher daily request tier (0002).
