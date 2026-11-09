# 0018. Drafting the gold set: sources, figure share, drafter model, sampling fixes

- **Status:** Accepted
- **Date:** 2026-11-09
- **Refines:** 0011 (how the "LLM drafts, owner verifies" gold set is produced). Sizes, splits and gates are unchanged.

## Context
0011 settled that a model drafts gold questions from sampled chunks and the owner verifies every one, writing the figure questions personally. It left the mechanics open. A 12-question pilot run (cost under a cent) and a scan of the first full draft turned up three problems in the drafter itself, plus three choices for the owner. No eval has run and no item had been verified, so the drafts could simply be thrown away and redone.

**Problems found:**
1. **Ambiguous subjects.** Every 10-K draft said "the company". Binding runs search every document (0017), so "what harm could the company suffer from its AI systems?" is answerable from Apple's, Microsoft's or J&J's risk factors. Recall would mark a correct retrieval as a miss.
2. **Truncated replies.** 4 of 12 pilot replies had no usable JSON, one of them empty. The drafter left hidden reasoning at the model's default. Reasoning tokens count against the 400-token cap, the same failure 0015 fixed for answers.
3. **A sampling bias.** The sampled chunks are sorted by chunk id, and the tail went to unanswerable questions. An unanswerable question uses its passage only as inspiration, so the documents ingested last lost their answerable slots. The first full draft had no answerable questions from FAA chapter 17 or the glossary, and Microsoft had 13 against 20 and 21 for the others.

## Options considered
**Which documents seed drafts** (retrieval still searches all of them)
- **Skip the handbook index and front matter.** The index is page-number lists and the front matter has 4 chunks. Even spreading across documents gives each about 3 junk drafts per run.
- **Also skip the glossary.** Cleaner gold pages, because a glossary definition usually repeats a chapter. But glossary-style lookups would go untested.
- **Draft from everything.** No code, but about 9 of 54 drafts would be rejected and topped up every time.

**How many FAA dev questions are figure questions** (the owner writes them; 10-Ks have no figure chunks)
- **12 of 60.** Enough for a rough figure-only score.
- **15 of 60.** Tighter, but more writing.
- **8 of 60.** Less work, but mostly noise.

**Which model drafts**
- **Claude Haiku 5.5, the generator.** The cheapest. Risk: a model can phrase questions in ways it finds easy to answer.
- **A bigger Claude model.** Better questions, perhaps. Same family, so the same risk.
- **Another family.** Removes the risk. Needs a ZDR endpoint (0009) outside the judge's family (0014).

## Decision
- **Skip `phak-index` and `phak-front`** by default (`draft_gold.py draft --skip-docs`). The glossary stays in. When a glossary answer also appears in a chapter, both pages go in the gold pages.
- **FAA dev: 12 owner-written figure questions plus 48 drafted. 10-K dev: 60 drafted.** About 10% of drafts are unanswerable (0011).
- **Haiku 5.5 drafts.** The same-model risk is accepted and recorded. Three things limit it: the owner reviews and rewrites every item, the prompt forces paraphrase, and the judge (another family) does the grading.
- **Drafter fixes.**
  - The prompt requires naming the company and fiscal year ("NAME THE SUBJECT").
  - The drafter turns reasoning off and names a reply cut off at `max_tokens`.
  - Unanswerable sources are a seeded random subset of the sample (`split_sources`), not the tail.
  - All three are pinned by tests. All earlier drafts were discarded and redrafted with the fixed tool. The 108 dev drafts cost about $0.017.

## Why
- **The drafter decides what the eval can measure.** A gold question with an ambiguous subject, or a set missing whole chapters, makes recall and coverage claims false, even when every metric is computed correctly. These are the same kind of construct-validity problem 0017 addressed in the runner.
- **A pilot was worth it.** It cost under a cent and found two of the three problems before 100 drafts were reviewed.
- **Haiku was enough.** The owner, not the drafter, is the quality gate. A stronger drafter would mostly save review time, at several times the cost.

## Consequences
- The owner still reviews every item. The checklist in `evals/README.md` covers trimming gold pages, adding the other pages that also answer, and checking unanswerables against the whole collection.
- **Held-out is not drafted yet.** `plan_counts(20)` gives 2 unanswerables per corpus, against a pooled minimum of 3 (`gates.toml [evidence]`). The proposal, still to be decided when held-out is drafted, is to over-draft and have the owner hand-add 1–2 unanswerables per corpus.
- Revisit the drafter model if review rejects many drafts for phrasing, or if eval results suggest drafted questions are easier for Haiku than owner-written ones. The `origin` field allows that comparison.
