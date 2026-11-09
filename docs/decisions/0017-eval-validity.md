# 0017. Eval validity: what the judge sees, unfiltered retrieval, evidence minimums

- **Status:** Accepted
- **Date:** 2026-11-09
- **Amends:** 0011 (how answers are judged, how the comparisons run) and 0016 (what makes a run binding, how much evidence a gate needs). Every threshold in 0016 is unchanged.

## Context
A code review before the gold set was built found four places where the eval would have measured something other than what its numbers claim. None of them is a bug in the usual sense: every test passed. They are validity problems, and they had to be settled now, because `evals/gates.toml` freezes once the first dev baseline exists (0016). At the time of writing there is no gold set and no eval has run, so nothing here was chosen after seeing a score.

1. **The judge graded faithfulness against less evidence than the generator had.** Faithfulness means "every claim in the answer is supported by what the generator was given". For a figure passage the generator is given the vision description *and* the image (0008). The judge was given only the description. An answer that reads a value correctly off a chart, where the description doesn't spell that value out, would be graded unfaithful. The FAA corpus has hundreds of figures and a per-corpus faithfulness gate of 0.90.
2. **The eval searched a smaller haystack than the product does.** The runner passed each question's corpus as a retrieval filter, so a 10-K question never competed with handbook chunks. The product searches everything unless the user picks a filter (0005). The gated numbers would have described a mode users have to opt into.
3. **A gate could pass on almost no evidence.** 0016 says a gate with *no* data is "not measured" and blocks. It set no floor above zero: kappa from four hand grades, or a held-out run of three questions, would have counted. Injection attacks that errored were dropped from the rate without blocking anything.
4. **Nothing tied the evidence together.** The release check combines a final run and two injection runs. Nothing checked they used the same generator and settings, so "resisted every attack" could have been measured on a different system from the one being released.

Separately, three of the six comparisons 0011 plans had no tooling (chunk size, embedder, figure image vs description only), and the embedder comparison would have been unfair: the Qwen query instruction was applied to every embedding model, including ones trained without it.

**Facts checked 2026-11-09** (OpenRouter's public `/api/v1/models` and `/api/v1/endpoints/zdr`): `openai/gpt-6-luna` lists `image` among its input modalities and has zero-data-retention endpoints on Azure. `openai/text-embedding-3-small` has a ZDR endpoint on Azure. The listing does not say whether the Azure ZDR endpoint accepts images in practice. That is confirmed, or not, by the judged smoke run.

## Options considered
**What the judge sees for a figure passage**
- **The same image the generator saw.** The judge grades against the full evidence. Costs image input tokens on each figure passage (an estimate of $0.0001–0.0002 per image at Luna's price). The owner's hand grades must then use the images too, or judge and human are doing different tasks.
- **Text only, with figure questions left out of the faithfulness gate.** No extra cost. The project's headline feature would then have no faithfulness gate.
- **Text only, bias documented.** Cheapest. FAA faithfulness would read low for a reason unrelated to the system.

**What retrieval the binding run uses**
- **Unfiltered binds; filtered is a comparison.** Measures the default product path. Scores may be slightly lower.
- **Filtered binds; unfiltered is a comparison.** Slightly flattering.
- **Filtered only.** The gap between eval and product stays unmeasured.

**Evidence minimums**
- **Minimums at about 75–80% of 0011's planned sizes.** Thin evidence blocks, but a few rejected gold items don't.
- **Minimums at exactly the planned sizes.** Strictest: one rejected question means writing a replacement before release.
- **No minimums; report n and leave it to the reader.**

**Comparison tooling**
- Build all four missing comparisons, or the three cheap ones and defer LLM-written context headers (one model call for each of about 3,450 chunks, plus a fourth index).

## Decision
- **The judge is sent the figure images the generator was sent,** each placed right after its passage, under the same zero-data-retention rule as every other call. `PipelineRun.figures` carries exactly those images out of the pipeline. Eval reports record, per retrieved passage, whether its image was sent.
- **The owner grades the same evidence.** `calibrate_judge.py grade` exports those images from the database to a gitignored folder and shows the path beside each figure passage. A missing image is an error, not a text-only grade.
- **The binding run searches every document.** `run_eval.py` no longer filters by corpus. `--corpus-filter` turns the filter on as a comparison, and a filtered run can't bind.
- **Evidence minimums,** in a new `[evidence]` table in `evals/gates.toml`, pinned by a test and frozen with the gates:

  | Evidence | Minimum | Planned size (0011) |
  |---|---|---|
  | Held-out answerable questions, per corpus | 15 | about 18 of 20 |
  | Held-out unanswerable questions, pooled | 3 | about 4 |
  | Hand grades for calibration | 25 | about 30 |
  | Direct injection attacks that ran | 12 | 15 |
  | Indirect attacks whose poisoned text reached the generator | 5 | 8 |

  Below a minimum, the release check reports an evidence problem and blocks, even if every point estimate clears its threshold. Questions and attacks that errored don't count towards a minimum, and any error in an injection run blocks.
- **One system.** Each injection run must match the final run on generator, reasoning setting, embedder, reranker, top-k and figure images. A mismatch blocks.
- **A partly embedded index can't be evaluated.** `run_eval.py` refuses to start if some chunks have no vector for the configured embedding model, and such a run could not bind.
- **Comparison tooling built:**
  - figure image vs description only: `run_eval.py --no-figure-images`
  - embedder: `scripts/embed_missing.py` adds a second model's vectors to the existing chunks; the query instruction is now applied only to models trained with one
  - chunk size: `scripts/make_chunk_index.py` builds `rag_chunk<N>`, copying the stored figure descriptions so no vision call is repeated; `run_eval.py --chunk-tokens N` runs against it
- **Deferred:** the LLM-written context header comparison. It stays on 0011's list as not done.

## Why
- **A metric is only as good as its definition of "evidence".** Faithfulness to the passages is meaningless if judge and generator disagree about what the passages contain. Sending the judge the images costs a fraction of a cent per run. Leaving them out would have put a systematic error into a gated number.
- **Gate the path users actually take.** A filter the user has to choose is a feature. It shouldn't be the condition the headline number depends on.
- **A threshold without a sample size is half a criterion.** "kappa ≥ 0.60" on four grades and on thirty are different claims. The minimums sit a little below the planned sizes because the owner will reject some drafted questions, and a release criterion that punishes careful review would be the wrong incentive.
- **Timing.** All of this lands before any gold item or score exists, so it keeps 0016's pre-registration honest instead of weakening it.

**What we trade away:**
- Judge cost and latency rise slightly on figure questions.
- Calibration now needs the database (to export images), and a re-ingest between a run and its hand-grading invalidates the sample.
- Unfiltered retrieval is a harder condition, so every retrieval-dependent gate is a little harder to pass.
- With about 20 held-out questions per corpus, a minimum of 15 still leaves wide confidence intervals. The minimums stop absurdly thin evidence; they don't make the estimate precise.

## Consequences
- The judged smoke run (`evals/README.md`) gains a figure-only pass (`run_eval.py --type figure --limit 3`), to confirm the Azure ZDR endpoint accepts images. If it doesn't, that needs a new record: a different judge, or figure questions leaving the faithfulness gate.
- `Judge.grade` takes the figures as a fourth argument. `RunConfig` gains `corpus_filter` and `figure_images`, and both appear in every report's configuration table.
- Chunk-size results can't be applied yet: `ingest_corpus.py` has no chunk-size option. If a comparison favours another size, adding that option and re-ingesting `rag` is its own decision.
- Three of the fifteen direct attacks have no canary (they ask for the system prompt). The judge's `injection_followed` is reported for them, but the canary gate doesn't measure them. That was already true under 0016 and is unchanged.
- The release check still doesn't compare the final run's configuration with what is deployed. That check belongs with the deployment decision.
- Revisit if the judge model changes (image support, price), if the product's default stops being "search everything", or if the gold set ends up much smaller than 0011 planned.
