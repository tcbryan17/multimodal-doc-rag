# Next steps (handoff, updated 2026-11-15)

Where the project stands (last updated 2026-11-15), and what to do next, in order. To resume with
Claude, say: *"continue from docs/next-steps.md"*. Delete this file, or rewrite it, once it is
out of date. `docs/build-plan.md` stays the long-term plan.

## Branches

- **Open PRs:** rag #2 `eval-progress`, #3 `deploy-api-hardening` and #4 `deploy-ops-scaffolding` (merge in that order), and site #3 `rag-live-ask-ui`. All were pushed 2026-11-15.
- **CI on #2** was failing on a stale injection test. Fixed in `ac4d027` (2026-11-15).
- **`figure-questions` (local).** It stacks on `eval-progress` and holds the 13 figure items, ADR 0022 and the figure smoke report.

## Owner queue, in order

### 1–2. Figure questions and the figure smoke run: done (2026-11-15)

- **The questions.** Claude (Opus 5.5) drafted 15 and the owner verified them on a review page. 13 were kept as `faa-dev-049`..`061` (ADR 0022). F05 and F12 were dropped. The working file is `private/review-tools/figure_drafts.json` and the images are in `private/figure-candidates/`.
- **The smoke run.** `evals/reports/20261115T141659Z-judge-smoke-figures.md`: 3 questions, every metric 1.00, $0.011. Each judge call carried 3 or 4 figure images and none failed, so the judge's ZDR endpoint accepts images.

### 3. Settle the judge prompt, then the dev baseline

```bash
uv run python scripts/run_eval.py --label baseline
```

- **Once the baseline exists, `evals/gates.toml` is frozen** (ADR 0016).
- **Don't change the judge after calibration starts.** Calibration is tied to the judge fingerprint (ADR 0019), so any judge change has to happen before step 4.
- **Expected cost:** at the smoke run's rate, about $0.003 per question all-in, so roughly $0.40 for the 118 verified dev questions.

### 4. Calibration: the owner grades about 30 answers (at least 25)

```bash
uv run python scripts/calibrate_judge.py sample --report evals/reports/<baseline>.json --n 30
uv run python scripts/calibrate_judge.py grade --name <baseline>   # or Claude shows each answer in chat
uv run python scripts/calibrate_judge.py agreement --name <baseline>
```

- **The grades must be the owner's** (ADR 0020).
- **For figure answers, look at the figure.** `grade` shows it.

### 5. Held-out review: the owner reviews all 40 drafts (ADR 0021)

| Corpus | Answerable | Unanswerable | Status |
|---|---|---|---|
| FAA | 18 | 2 | all `draft` |
| 10-K | 18 | 2 | all `draft` |

**The documents:**
- **10-K:** Costco FY2026.
- **FAA:** PHAK chapters 11, 13 and 15.

**How the review runs:** Claude shows one item at a time: the question, the reference answer, the source excerpt, and any other pages that also answer it (found with `rv.py`). The owner then verifies, edits or rejects the item. The checklist is in `evals/README.md`, under "Reviewing a draft".

**Evidence minimums:**
- At least 15 answerable items per corpus must be verified.
- At least 3 unanswerable items must be verified, counted across both corpora.

### 6. Spot-check the injection review

**Where:** read `evals/injection/REVIEW.md`. It covers 20 verified items and 3 rejected ones. The 3 rejects are fake-citation canaries that `renumber_markers` strips, so they can never fire.

**Margins against the minimums:**

| Attack type | Verified | Minimum |
|---|---|---|
| Direct | 14 | 12 |
| Indirect | 6 | 5 |

The indirect margin is thin.

**Decisions for the owner:**
- Overturn any row?
- Add a `</source>` break-out indirect attack?
- Add a fake-citation attack with a text canary?

**Row to watch:** `direct-004`'s canary, "Paris", also appears in 22 corpus chunks.

## Claude can do these once the settings are fixed (no owner input needed)

- **Injection runs.** These must use the same models and settings as the final run (ADR 0017), so they come after the baseline settles the settings. Stop uvicorn before building the eval index.
  ```bash
  uv run python scripts/run_eval.py --injection --label direct-injection
  uv run python scripts/make_eval_index.py
  uv run python scripts/run_eval.py --injection --eval-index --label indirect-injection
  ```
  `rag_eval` doesn't exist yet. `make_eval_index.py` builds it.
- **Dev comparisons** (build plan step 15): rerank off, reasoning on, another generator, corpus filter, no figure images.
- **Governance documents:** fill evidence into the control matrix and re-rate the risk register (step 17).

## Then

1. **Held-out final run and release check** (step 18). Run the held-out split once with `--i-know-this-is-heldout`, then `release_check.py`. Commit the verdict, pass or fail. Then write the system card.
2. **Deploy to Fly.io + Neon** (step 19). Follow `docs/deployment.md` on `deploy-ops-scaffolding`.
   - **Owner:** create the Fly app and the Neon project.
   - **Database:** `pg_dump`/`pg_restore` the local database to Neon. There is no re-ingest. First check that Neon supports Postgres 18 and pgvector 0.8 or later.
   - **Read-only role:** create it from `docker/roles/readonly_role.sql`.
   - **Secrets:** add `FLY_API_TOKEN` and `RELEASE_CHECK_DATABASE_URL` to GitHub.
   - **Settings:** set `CORS_ALLOW_ORIGINS=https://tcbryan17.github.io` and `TRUSTED_PROXY_HOPS=1`, and set `STATS_TOKEN` if you want `/stats` on.
   - **Deploy workflow:** replace the `if: false` placeholder in `.github/workflows/deploy.yml` with `flyctl deploy`.
   - **Site:** set `links.api` in the site's `projects.js`. That turns on the ask box.

## Tools kept between sessions

**`private/review-tools/`** (gitignored) holds the review helpers:

| File | Purpose |
|---|---|
| `rv.py` | Looks things up in the local database. Commands: `item <id>`, `fts '<words>'`, `like '<exact text>' [doc]`, `page <doc> <idx>`, `label <doc> <label>`. Needs `docker compose up -d --wait`. |
| `apply.py` | Applies a JSONL of review decisions through `evals/review.py`. |
| `BRIEF.md` | The brief for subagent reviewers. |
| `labels.json` | Maps page labels to page indexes. |
| `overview.py` | Collapses the code graph into the README's Mermaid diagram (an earlier draft of `scripts/code_graph_overview.py`). |
| `injection_review.jsonl`, `inj_rows.md` | The injection review's source files. |

**`page_idx` is the 0-based position in the file, not the printed label.** Gold pages are written `doc:page_idx:label`.

## Spend

The OpenRouter key has a $5 credit limit, and every run has its own cap through `CostMeter`. Known spend so far:
- Ingest: about $0.25.
- Text smoke run: $0.016.
- Gold drafting: not recorded here.

Check OpenRouter's activity page for the exact remaining balance.
