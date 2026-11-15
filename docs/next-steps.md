# Next steps (handoff, 2026-11-14)

Where the project stands at the end of 2026-11-14, and what to do next, in order. To resume with
Claude, say: *"continue from docs/next-steps.md"*. Delete this file, or rewrite it, once it is
out of date. `docs/build-plan.md` stays the long-term plan.

## Branches waiting for review

PRs #1 (rag) and #2 (site) are merged. Four branches are **local only, not pushed**. All of them
start from `cb611e7` and merge cleanly with each other (checked pairwise with `git merge-tree`).

| Branch | Repo | Contents |
|---|---|---|
| `eval-progress` | multimodal-doc-rag | Injection review (`evals/injection/REVIEW.md`), the 40 held-out drafts, the judged smoke-run report, and this file. It also carries `cb611e7` (README: current stack and status), which was pushed after PR #1 had merged and so is **not yet on `main`**. |
| `deploy-api-hardening` | multimodal-doc-rag | CORS, per-IP rate limits, a daily spend cap, `/stats`, input caps; ADR 0021 (Fly.io + Neon, question text never logged, review owners). |
| `deploy-ops-scaffolding` | multimodal-doc-rag | Non-root Dockerfile, read-only DB role, manual deploy-gate workflow, `docs/deployment.md` runbook (updated for ADR 0021). |
| `rag-live-ask-ui` | portfolio-site | The "ask your own question" UI, hidden until the project's `links.api` is set. It also carries `6c8238c` (site README update), which missed PR #2's merge. |

Suggested merge order:
1. `eval-progress`.
2. `deploy-api-hardening`, which adds ADR 0021.
3. `deploy-ops-scaffolding`, whose runbook links ADR 0021.

The site PR can go any time.

To push and open a PR: `git push -u origin <branch>`, then `gh pr create`.

## Owner queue, in order

### 1. Write the FAA figure questions (12; the first 3 unblock the figure smoke run)

**Send:** lines like `F04 | Q: According to the FAA Pilot's Handbook's carburetor icing chart, … ? | A: …`.

**Where the candidates are:** the images are in `private/figure-candidates/` (gitignored). Open them with `open private/figure-candidates`.

**What Claude does with them:** adds each one with `owner_item` (origin `owner`, status `verified`, type `figure`) and uses the gold page from the table below.

| # | Gold page (`doc:page_idx:label`) | Chunk | What it shows |
|---|---|---|---|
| F01 | `phak-ch05:3:5-4` | 1766 | CL/CD vs angle of attack graph |
| F02 | `phak-ch05:33:5-34` | 1905 | Load factor vs bank angle |
| F03 | `phak-ch05:37:5-38` | 1917 | Vg diagram |
| F04 | `phak-ch07:9:7-10` | 2082 | Carburetor icing chart |
| F05 | `phak-ch07:34:7-35` | 2206 | Atmospheric pressure (psi) table |
| F06 | `phak-ch08:8:8-9` | 2278 | Airspeed indicator markings |
| F07 | `phak-ch08:4:8-5` | 2260 | Height above airport table |
| F08 | `phak-ch08:24:8-25` | 2361 | Compass correction card |
| F09 | `phak-ch10:7:10-8` | 2467 | Loading graph |
| F10 | `phak-ch10:7:10-8` | 2468 | CG moment envelope |
| F11 | `phak-ch12:5:12-6` | 2628 | Takeoff distance vs pressure altitude |
| F12 | `phak-ch12:11:12-12` | 2651 | Wind symbols |
| F13 | `phak-ch14:2:14-3` | 2810 | Communication procedures table |
| F14 | `phak-ch05:25:5-26` | 1864 | Stall speed / load factor vs bank |
| F15 | `phak-ch10:8:10-9` | 2470 | Loading schedule placard |

Good figure questions need the figure to answer them, for example by reading a value off a chart. If the caption or body text already gives the answer, the question isn't testing the figure.

### 2. Figure smoke run (Claude, a few cents)

```bash
uv run python scripts/run_eval.py --corpus faa --type figure --limit 3 --label judge-smoke-figures
```

This run confirms that the judge's zero-data-retention endpoint accepts images.

The text smoke run already passed: `evals/reports/20261114T161029Z-judge-smoke.md`, 5 questions, every metric 1.00, $0.0028 per question, p95 latency 2.9 s, judge fingerprint `e2a908a51730`.

### 3. Settle the judge prompt, then the dev baseline

```bash
uv run python scripts/run_eval.py --label baseline
```

- **Once the baseline exists, `evals/gates.toml` is frozen** (ADR 0016).
- **Don't change the judge after calibration starts.** Calibration is tied to the judge fingerprint (ADR 0019), so any judge change has to happen before step 4.
- **Expected cost:** at the smoke run's rate, about $0.003 per question all-in, so roughly $0.40 for the ~117 dev questions.

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
