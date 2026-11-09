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

## Workflow

Prerequisites: an `OPENROUTER_API_KEY` in `.env` (project-only key, $5 credit limit), the
corpus fetched and ingested. The judge defaults to `openai/gpt-6-luna` (see below).

```bash
# 1. Draft a gold set: a model writes questions from sampled pages (seeded, reproducible)
uv run python scripts/draft_gold.py draft --corpus faa --split dev --n 60
uv run python scripts/draft_gold.py draft --corpus 10k --split dev --n 60

# 2. Review EVERY draft: [v]erify, [e]dit, [r]eject, [s]kip. Saved after each decision.
uv run python scripts/draft_gold.py review --corpus faa
uv run python scripts/draft_gold.py review --corpus 10k
#    Write the figure questions yourself (the model skips figures on purpose):
uv run python scripts/draft_gold.py add --corpus faa --type figure
#    Repeat drafting with --split heldout for the held-out questions (20 per corpus).

# 3. Run the eval (dev split). Smoke test first, cheap and judge-free:
uv run python scripts/run_eval.py --corpus faa --limit 5 --no-judge --label smoke
#    Then a judged smoke run, before any full run. Check the report for: zero judge errors,
#    and a judge cost of roughly $0.0005 per item. Empty judge replies mean the reasoning
#    model spent its output cap (OpenRouterJudge max_tokens); a rejected request may mean
#    the endpoint refused `temperature` (ADR 0014).
uv run python scripts/run_eval.py --corpus faa --limit 5 --label judge-smoke
uv run python scripts/run_eval.py --label baseline
uv run python scripts/run_eval.py --label rerank-off --no-rerank        # a comparison
uv run python scripts/run_eval.py --label reasoning-on --reasoning      # ADR 0015 comparison

# 4. Injection tests
uv run python scripts/draft_gold.py review-injection --kind direct      # verify my drafts
uv run python scripts/draft_gold.py review-injection --kind indirect
uv run python scripts/run_eval.py --injection --label direct-injection  # direct ones, real index
uv run python scripts/make_eval_index.py                                # stop uvicorn first
uv run python scripts/run_eval.py --injection --eval-index --label indirect-injection

# 5. Calibrate the judge: grade ~30 answers blind, then compare with the judge
uv run python scripts/calibrate_judge.py sample --report evals/reports/<run>.json --n 30
uv run python scripts/calibrate_judge.py grade --name <run>
uv run python scripts/calibrate_judge.py agreement --name <run>

# 6. At the very end, once: the held-out split
uv run python scripts/run_eval.py --split heldout --i-know-this-is-heldout --label final
```

`JUDGE_MODEL` defaults to `openai/gpt-6-luna` (ADR 0014): a **different family** from every
generator being compared (Claude, Gemma and Qwen), with a zero-data-retention endpoint. The
runner refuses a same-family judge. `--no-judge` skips judging.

Every run is capped by `--budget` (default `EVAL_BUDGET_USD`). If the cap trips, the run
stops and still writes a partial report that says it was cut short.

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
  or not it is true in the real world. "I don't know" is faithful.
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

- Tune on **dev** only. The held-out split is scored once at the end; the runner makes you
  say so with `--i-know-this-is-heldout`.
- Runs only include `status: verified` items. `--include-drafts` is a smoke test and the
  report says so loudly.
- A gold item's split must match its documents' split in `data/manifest.json`; the runner and
  the drafter check this.
- The poisoned document exists only in `rag_eval`, never in `rag`.
