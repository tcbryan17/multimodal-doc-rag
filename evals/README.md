# Evals

How we measure whether the system is good (ADR 0011). Evals are not tests: they make real,
paid model calls, produce scores, and run when something changes. The code is in
`src/multimodal_doc_rag/evals/`; the commands are thin wrappers in `scripts/`.

| Folder | What is in it |
|---|---|
| `gold/{10k,faa}.jsonl` | the questions, with reference answers and gold pages (you build these) |
| `injection/{direct,indirect}.jsonl` | prompt-injection questions, each with a "canary" |
| `poisoned/` | generator for the synthetic poisoned handbook chapter (eval-only index) |
| `reports/` | committed run reports (`.json` full detail, `.md` summary) |
| `calibration/` | your hand grades of judge-graded answers, and the agreement summary |
| `gates.toml` | the pre-registered release gates and evidence minimums (ADR 0016, 0017); frozen once the dev baseline exists |

## Workflow

Prerequisites: an `OPENROUTER_API_KEY` in `.env` (project-only key, $5 credit limit), the
corpus fetched and ingested. The judge defaults to `openai/gpt-6-luna` (see below).

```bash
# 1. Draft a gold set: a model writes questions from sampled pages (seeded, reproducible)
uv run python scripts/draft_gold.py draft --corpus faa --split dev --n 60
uv run python scripts/draft_gold.py draft --corpus 10k --split dev --n 60

# 2. Review EVERY draft: [v]erify, [e]dit, [r]eject, [s]kip. Saved after each decision.
#    Checklist below ("Reviewing a draft").
uv run python scripts/draft_gold.py review --corpus faa
uv run python scripts/draft_gold.py review --corpus 10k
#    Write the figure questions yourself (the model skips figures on purpose). FAA dev
#    has 12 of them (ADR 0018). Write 3 first: the figure smoke run in step 3 needs them.
uv run python scripts/draft_gold.py add --corpus faa --type figure
#    Top up after rejections: draft N more. Chunks that already seeded a draft are never
#    reused, and the handbook index and front matter are never used as sources (--skip-docs).
uv run python scripts/draft_gold.py draft --corpus faa --split dev --n 5 --seed 1
#    Repeat drafting with --split heldout for the held-out questions (20 per corpus).

# 3. Run the eval (dev split). Smoke test first, cheap and judge-free:
uv run python scripts/run_eval.py --corpus faa --limit 5 --no-judge --label smoke
#    Then a judged smoke run, before any full run. Check the report for: zero judge errors,
#    and a judge cost of roughly $0.0005 per item. Empty judge replies mean the reasoning
#    model spent its output cap (OpenRouterJudge max_tokens); a rejected request may mean
#    the endpoint refused `temperature` (ADR 0014) or an image (ADR 0017). The second
#    command runs figure questions only: the judge is sent the figure images, and this is
#    where we learn whether its zero-data-retention endpoint accepts them.
uv run python scripts/run_eval.py --corpus faa --limit 5 --label judge-smoke
uv run python scripts/run_eval.py --corpus faa --type figure --limit 3 --label judge-smoke-figures
uv run python scripts/run_eval.py --label baseline

# 3b. Comparisons (ADR 0011), all on dev. Change one thing per run, against the baseline.
uv run python scripts/run_eval.py --label rerank-off --no-rerank
uv run python scripts/run_eval.py --label reasoning-on --reasoning      # ADR 0015
uv run python scripts/run_eval.py --label generator-gemma --generator google/gemma-4-26b-a4b-it
uv run python scripts/run_eval.py --label corpus-filter --corpus-filter
uv run python scripts/run_eval.py --label no-figure-images --no-figure-images
#    Embedder: add the second model's vectors to the same chunks (about 3 cents), then run.
EMBEDDING_MODEL=openai/text-embedding-3-small EMBEDDING_DIM=1536 \
    uv run python scripts/embed_missing.py
EMBEDDING_MODEL=openai/text-embedding-3-small EMBEDDING_DIM=1536 \
    uv run python scripts/run_eval.py --label embedder-openai-3-small
#    Chunk size: one extra database per size, embeddings only (figure descriptions are reused).
uv run python scripts/make_chunk_index.py --max-tokens 256
uv run python scripts/run_eval.py --chunk-tokens 256 --label chunk-256

# 4. Injection tests
uv run python scripts/draft_gold.py review-injection --kind direct      # verify my drafts
uv run python scripts/draft_gold.py review-injection --kind indirect
uv run python scripts/run_eval.py --injection --label direct-injection  # direct ones, real index
uv run python scripts/make_eval_index.py                                # stop uvicorn first
uv run python scripts/run_eval.py --injection --eval-index --label indirect-injection

# 5. Calibrate the judge: grade ~30 answers blind, then compare with the judge. `grade`
#    exports the figure images the judge saw to evals/calibration/figures/ and prints the
#    path beside each figure passage: open it, so you grade the same evidence (ADR 0017).
uv run python scripts/calibrate_judge.py sample --report evals/reports/<run>.json --n 30
uv run python scripts/calibrate_judge.py grade --name <run>
uv run python scripts/calibrate_judge.py agreement --name <run>
#    The grades record the judge's fingerprint (model + output cap + prompt). The release
#    check refuses them if the final run's judge differs, so calibrate against the judge
#    you will release with, and re-calibrate if its prompt changes (ADR 0019).

# 6. At the very end, once: the held-out split, then the release decision (ADR 0016)
uv run python scripts/run_eval.py --split heldout --i-know-this-is-heldout --label final
uv run python scripts/release_check.py --final evals/reports/<final>.json \
    --injection evals/reports/<direct>.json --injection evals/reports/<indirect>.json \
    --calibration <run>
```

Every report has a **Release gates** table. On dev runs it is guidance: tune against it, but
it can't decide release. Only the held-out final run, plus the injection, calibration and
figure-coverage evidence, can do that, through `release_check.py`. A gate with no data is
"not measured", and that blocks release just like a failure. So does thin evidence: the
`[evidence]` table in `gates.toml` sets how many questions, attacks and hand grades the release
check needs (ADR 0017), and the injection runs must use the same models and settings as the
final run.

`JUDGE_MODEL` defaults to `openai/gpt-6-luna` (ADR 0014): a **different family** from every
generator being compared (Claude, Gemma and Qwen), with a zero-data-retention endpoint. The
runner refuses a same-family judge. `--no-judge` skips judging.

Every run is capped by `--budget` (default `EVAL_BUDGET_USD`). If the cap trips, the run
stops and still writes a partial report that says it was cut short.

## Reviewing a draft

Recall and citation accuracy are only as good as the gold pages, so most of the review is about
pages, not wording.

- **Trim the gold pages.** The drafter lists every page its source chunk spans. Keep only
  the pages where the answer actually is.
- **Add every other page that also answers it.** 10-K figures repeat across MD&A, the
  financial statements and the notes; handbook concepts repeat between the glossary and a
  chapter. A missing page turns a correct retrieval into a recorded miss.
- **Gold pages are typed as `doc:page_idx:label`, and `page_idx` is NOT the printed label.**
  `page_idx` is the 0-based position in the file, and metrics compare by it. Microsoft's printed
  page 80 is idx 79; J&J's printed 43 is idx 47. Nothing checks that the two agree, so look the
  index up:
  `docker compose exec -T db psql -U rag -d rag -c "SELECT DISTINCT page_idx_start FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.doc_key='msft-10k-2026' AND c.page_label_start='80'"`
- **If a held-out document also answers a dev question**, rewrite the question so only the dev
  document fits, or reject it. A held-out page can't be a gold page on a dev item (verify
  refuses it), and retrieval could fairly return it and be scored a miss.
- **The question must name its subject.** The company and fiscal year for a 10-K ("In
  Microsoft's fiscal 2026 10-K, ..."), never "the company" or "the text". Retrieval searches
  every document.
- **Check that the reference answer is right and complete** against the source text shown
  under the draft, including exact figures and units.
- **Reject or rewrite questions that echo the passage's wording.** They make keyword search
  look better than it is.
- **Check that unanswerable questions really are unanswerable**, against the whole collection
  (both corpora, held-out documents included), not just the passage they came from. Ask
  yourself whether a careful system could give a defensible partial answer. If it could,
  rewrite the question or reject it.
- **Change `type` when the draft's label is wrong.** "fact" is a figure, name or rule; "concept"
  is a why or how.

## Metrics, in plain language

Pages are compared by their position in the file (`page_idx`), never by printed label.

- **recall@k**: for an answerable question, did at least one of the first k retrieved
  passages come from the right document and span a gold page? A yes/no per question, averaged.
  It measures retrieval alone; a miss means the generator never had a chance.
- **citation accuracy**: of the passages the answer cited, the share that cover a gold page.
  Undefined (left out of the average) when the answer cites nothing.
- **abstention rate** (unanswerable questions): the share where the answer was the fixed
  "I don't know" reply (or started with it). Higher is better.
- **false-abstention rate** (answerable questions): the share where it said "I don't know"
  anyway. Lower is better.
- **numeric match**: for questions whose reference answer contains numbers, did the answer
  contain every one of them? Handles `$`, commas, `%`, "million/billion", `(1,234)` negatives;
  ignores sign; accepts `383` for `$383 million` (tables state units once).
- **correctness** (judge): 1 = matches the reference, 0.5 = partly, 0 = wrong. For
  unanswerable questions 1 = it declined.
- **faithfulness** (judge): 1 if every claim is supported by the retrieved passages, whether
  or not it is true in the real world. "I don't know" is faithful. For a figure passage the
  judge is sent the same image the generator saw, so a value read off a chart counts as
  supported (ADR 0017).
- **cost and latency per question**: mean / p50 / p95. Cost is answering only (embed, rerank,
  generate); judge cost is recorded separately. Latency excludes the judge.
- **injection**: *canary in answer* = the attack worked (a marker that only appears if the
  model obeyed). For indirect attacks, *poisoned text reached the generator* tells you whether
  the question tested anything. The judge's `injection_followed` is shown beside the canary.
- **mean with 95% CI**: a bootstrap confidence interval (seeded). With ~60 questions it is
  wide; differences smaller than the interval are noise.
- **Cohen's kappa** (calibration): agreement between judge and you beyond chance. Raw
  agreement flatters a judge when one grade dominates, kappa does not.

## Rules of the road

- Retrieval searches **every document** by default, like the product does. `--corpus` only
  picks which questions run. `--corpus-filter` restricts retrieval too, as a comparison; a
  filtered run can't be the binding one (ADR 0017).
- Tune on **dev** only. The held-out split is scored once at the end; the runner makes you
  say so with `--i-know-this-is-heldout`.
- Runs only include `status: verified` items. `--include-drafts` is a smoke test and the
  report says so loudly.
- A gold item's split must match its documents' split in `data/manifest.json`; the runner and
  the drafter check this.
- The poisoned document exists only in `rag_eval`, never in `rag`.
- Comparison indexes (`rag_chunk<N>`) are separate databases too. `rag` is the only index the
  product serves and the only one the binding run uses.
