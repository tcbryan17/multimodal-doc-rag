# 0018. Gold set composition and how drafts are sampled

- **Status:** Accepted
- **Date:** 2026-11-13
- **Amends:** 0011 (fills in the question mix inside its sizes, and replaces the draft sampling rule). Sizes, metrics and gates are unchanged.

## Context
0011 fixes the size of the gold set (60 dev + 20 held-out per corpus, about 10% unanswerable) and the three question types (fact, figure, concept). It doesn't say how many of each, or which pages questions come from. Both have to be settled before drafting starts, because the gold set is what every gated number is measured on, and `evals/gates.toml` freezes once the dev baseline exists (0016).

Four facts shaped the choice:

1. **The 10-Ks contain no figures.** The ingest found 0 images in all four filings. Figure questions can only come from the handbook. The 10-Ks' hard case is tables: about 25–30% of each filing's chunks are tables, and that's where the numeric-match metric does its work.
2. **The drafter gave every document the same number of questions.** Its round-robin sampler visited documents in turn. The handbook's dev split has 20 documents, so each got about 3 of 54 drafts, whether it was Ch. 5 (151 chunks), Ch. 4 (32 chunks), the 7-chunk front matter or the back-of-book index. Questions drafted from the index are about page numbers, and they would have been a sizeable part of the set.
3. **The unanswerable seeds came from one document.** The sample was sorted by chunk id and the last few became unanswerable seeds. Chunk ids follow ingest order, so for the 10-K dev split they were likely all Microsoft passages.
4. **The unanswerable prompt could produce answerable questions.** It suggested asking about "a company the collection does not cover", but the model only saw one passage. Costco and handbook chapters 11, 13 and 15 are held out from *tuning*, not from the index, and binding runs search every document (0017). So a dev "unanswerable" question about Costco would actually be answerable.

## Options considered
**Question mix**
- **Whatever the drafter produces.** No planning. But figure questions are written by hand, so their number would be arbitrary, and the drafter's fact/concept choice can't be steered.
- **Proportional to content.** Figures are 25% of the handbook's dev chunks (432 of 1,725, from the dry-run report), which would mean about 13 figure questions. That's close to a usable size, but only by accident, and the held-out chapters would get about 4.
- **Fixed targets per category,** sized so each headline category can be read on its own. For the handbook this lands near the proportional count (15 vs 13 in dev), so the figure category is barely over-weighted.

**Which pages questions come from**
- **Equal share per document** (the old rule).
- **Proportional to size,** with every document covered once when there are enough questions.
- **Hand-set quotas per chapter.** Precise, but every number would need its own justification.

**How to count table questions**
- **A new `subtype` field in the gold schema.** Clean, but it changes the schema and the drafted file format for one corpus's use.
- **A fixed marker in `notes`** ("source: table"), written by the drafter and by `add --table`. No schema change. The owner must keep the marker when editing notes.

## Decision
**Targets** (verified items):

| Corpus | Split | Unanswerable | Figure | Fact (table) | Fact (prose) | Concept | Total |
|---|---|---|---|---|---|---|---|
| Handbook | dev | 6 | 15 | – | 21 | 18 | 60 |
| Handbook | held-out | 2 | 6 | – | 7 | 5 | 20 |
| 10-K | dev (18 per company) | 6 | – | 24 | 12 | 18 | 60 |
| 10-K | held-out (Costco) | 2 | – | 8 | 4 | 6 | 20 |

Handbook fact questions aren't split into table and prose: its tables are mostly images, so they count as figure questions. Handbook held-out answerable questions are spread roughly by chapter size: Ch. 11 ≈ 8, Ch. 13 ≈ 7, Ch. 15 ≈ 3.

**Figure questions** (owner-written):
- A figure question is one whose answer needs the figure: a value read off a chart or table image, or a relationship only the diagram shows.
- **At least 4 of the 15 dev figure questions** must have answers visible in the image but **missing from the stored vision description**. Without them, the `--no-figure-images` comparison (0017) can't show a difference, because every answer would also be in the text.
- Avoid the three figures that stayed caption-only after the ingest. A question about one of those would test the degraded path, which is a separate question from figure reading.

**Unanswerable questions:** aim for about a third each of three kinds:
- wrong period or entity
- the topic is covered but the specific number isn't reported (the hardest kind)
- a plausible adjacent topic the documents never discuss

The review rejects any question that a held-out document answers.

**Sampling** (`evals/draft.py`):
- Each document first gives one random chunk, when there are enough drafts to go round. The rest is a simple random sample of all remaining chunks. So a document's expected share is proportional to its chunk count.
- Front matter and the index (`NAVIGATION_DOCS`) are never drafted from. They stay in the index, where they compete in retrieval as distractors.
- Unanswerable seeds are a random subset of the sample.
- The unanswerable prompt lists every document title in the index, from both corpora.
- `--kind table|text` drafts from one chunk kind, to top up a category. `--unanswerable N` sets how many unanswerable questions to draft.
- Drafts from table chunks carry the `source: table` marker. `draft_gold.py count` shows progress against the targets.

**Order of work:** write the held-out items **before the first dev eval run**. They are scored once, at the end, either way. Writing them before seeing any score means the questions can't drift, even unconsciously, towards what the system already does well.

## Why
- **Each headline category needs enough questions to be read on its own.** 15 dev figure questions gives a 95% interval of roughly ±0.2 on a proportion near 0.8. Fewer, and the figure numbers would be noise. More, and they'd crowd out the text questions they're compared against.
- **Proportional sampling matches what users meet.** A question is more likely to concern a long chapter than a short one. Equal shares over-weighted short and navigational documents. Covering every document once keeps small chapters from vanishing at random.
- **Tables are the 10-K's multimodal content.** Making them 40% of answerable 10-K questions, against about 25% of chunks, puts the weight where the parser and the numeric checks are tested hardest. This is a deliberate over-sample, and it's stated here so it can be defended.
- **Fixing the unanswerable prompt cuts wasted review.** Every unanswerable draft that turns out to be answerable costs a rejection and a top-up.

**What we trade away:**
- The mix is our judgement, not a sample of real user questions. There are no real users yet.
- The table marker lives in free text, so an edit can drop it. `count` makes that visible.
- Over-sampling tables means the pooled 10-K score leans towards table performance. The per-type rows in each report separate the two.
- Owner workload: about 21 hand-written figure questions, and review of about 180 drafts, counting the over-draft.

## Consequences
- Draft about 1.4× each target, because review rejects some, then top up with a new `--seed` (used chunks are skipped). The exact commands are in `evals/gold/README.md`.
- The fact-vs-concept balance is set in review, by rejecting surplus, because the drafting model chooses the type.
- Reports already show a `corpus / split / type` row. Table vs prose is counted by `draft_gold.py count`, not broken out in reports. Add that only if the dev baseline shows tables and prose behaving differently.
- Revisit if a re-ingest adds figures to the 10-Ks, or if real usage logs (after deployment) show a different mix of questions.
