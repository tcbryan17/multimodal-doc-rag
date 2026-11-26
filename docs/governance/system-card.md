# System card (skeleton)

Draft for owner review (2026-11-26)

This is the skeleton promised in [ADR 0016](../decisions/0016-governance-and-release-gates.md). Evaluation results are filled in only after the held-out run. Items marked `TODO(owner)` need the owner's words or decision. Nothing is deployed yet.

## 1. Intended use

- A public demo that answers plain-English questions over two fixed document sets: SEC 10-K filings (Apple, Microsoft, Johnson & Johnson; Costco held out) and the FAA *Pilot's Handbook of Aeronautical Knowledge* (FAA-H-8083-25C). See the [README](../../README.md) and [ADR 0004](../decisions/0004-corpora-10k-and-faa-handbook.md).
- Question types: fact lookup, reading a figure, explaining a concept ([ADR 0005](../decisions/0005-ux-and-ask-contract.md)).
- Every answer carries page-level citations using printed page labels, and figure answers show the figure.
- `TODO(owner)`: one sentence on why this demo exists, for the card's first paragraph.

## 2. Out of scope

- Financial, legal or flight-training advice. The UI disclaimer says so ([README](../../README.md)).
- Any document outside the corpus, any later filing, and any handbook edition other than 25C ([data card, section 1](data-card.md)).
- Private or personal data. The system is for public documents only.
- Taking actions. The model has no tools ([C29](control-matrix.md)).
- Safety-critical use, including flight planning or operations.
- High-risk uses under the EU AI Act. The classification is in the [governance README](README.md).

## 3. Users

Visitors to the portfolio site, such as hiring managers and engineers. No accounts, no sign-in. Per-IP rate limits and a daily spend cap are planned for the live API ([C26](control-matrix.md)). `TODO(owner)`: state the intended audience in your own words.

## 4. Models and versions

Model ids are as set in [`config.py`](../../src/multimodal_doc_rag/config.py). Ids live in config, never in code ([ADR 0009](../decisions/0009-models-and-privacy.md)). All calls go through OpenRouter with zero data retention ([ADR 0002](../decisions/0002-openrouter-for-all-model-calls.md), C16).

| Role | Model id in `config.py` | Notes |
|---|---|---|
| Embedding | `qwen/qwen3-embedding-8b` | 1,024 dimensions (`embedding_dim`), re-normalised |
| Reranking | `qwen/qwen3-reranker-8b` | On failure, hybrid-search order is kept ([C28](control-matrix.md)) |
| Answer generation | `anthropic/claude-haiku-5.5` | Hidden reasoning off (`generation_reasoning = False`, [ADR 0015](../decisions/0015-reasoning-off-and-output-caps.md)) |
| Figure description (ingest) | `anthropic/claude-haiku-5.5` | Hidden reasoning off (`vision_reasoning = False`) |
| Eval judge (offline only) | `openai/gpt-6-luna` | Different model family from the generator ([ADR 0014](../decisions/0014-judge-model.md)) |

Other components: Postgres with pgvector, hybrid search fused with Reciprocal Rank Fusion ([ADR 0010](../decisions/0010-database-access-schema-search.md)), our own retrieval code with no framework ([ADR 0001](../decisions/0001-hand-rolled-retrieval.md)).

`TODO(owner)`: record the model versions or dates actually served at the time of the held-out run. OpenRouter ids may point to changing backends.

## 5. Data

See the [data card](data-card.md). In short: 25 source files in two corpora, fetched by script from sec.gov and faa.gov, 3,449 chunks of which 496 are figures, with 493 of 496 figures described (99.4%). Counts are as of 2026-11-09. Personal data: public-role names in 10-Ks only. See [gdpr.md](gdpr.md).

## 6. Evaluation

Filled after the held-out run. Gates and thresholds are pre-registered in [`evals/gates.toml`](../../evals/gates.toml) ([ADR 0016](../decisions/0016-governance-and-release-gates.md), [0017](../decisions/0017-eval-validity.md)).

| Gate | Threshold | Result | Pass |
|---|---|---|---|
| recall@5 (per corpus) | 0.80 or more | TODO(owner): filled after the held-out run | |
| citation accuracy (per corpus) | 0.90 or more | filled after the held-out run | |
| faithfulness (per corpus) | 0.90 or more | filled after the held-out run | |
| correctness (per corpus) | 0.75 or more | filled after the held-out run | |
| false abstention (per corpus) | 0.10 or less | filled after the held-out run | |
| abstention on unanswerable (pooled) | 0.80 or more | filled after the held-out run | |
| mean cost per question (per corpus) | $0.005 or less | filled after the held-out run | |
| p95 latency (per corpus) | 8,000 ms or less | filled after the held-out run | |
| injection canary rate | 0 | filled after the injection runs | |
| judge vs owner kappa | 0.60 or more | filled after calibration | |
| figure coverage | 0.99 or more | 0.994 on 2026-11-09 (database count, not the binding check) | |

Also record: sample sizes against the [evidence minimums](../../evals/gates.toml), 95% confidence intervals, the release-check verdict, the judge fingerprint ([ADR 0019](../decisions/0019-calibration-tied-to-judge.md)), and who reviewed the gold set ([ADR 0020](../decisions/0020-dev-gold-set-reviewed-by-claude.md), [0021](../decisions/0021-deployment-hosting-logging-and-review-owners.md), [0022](../decisions/0022-figure-questions-drafted-by-claude.md)).

## 7. Known limitations today

From the repo as of 2026-11-26:

- **Figure crops.** About 3 of 73 crops were visibly wrong in the parser comparison, and only 2 of 17 chapters were tested ([ADR 0006](../decisions/0006-parsing.md)).
- **Caption-only figures.** 3 of 496 figures kept only their caption after the vision call failed ([data card, section 5](data-card.md)).
- **Misread descriptions.** Two stored vision descriptions misread their figures (F06 and F14, [risk register R5](risk-register.md)). The generator also gets the image, which limits the damage.
- **Refusal is prompt-based.** Beyond the fixed answer when nothing is retrieved ([C8](control-matrix.md)), "I don't know" depends on the system prompt rule and the model following it. It is measured by the abstention gate, on few unanswerable questions ([R2](risk-register.md)).
- **Judge and generator temperature.** The catalogue does not list `temperature` for the judge ([ADR 0014](../decisions/0014-judge-model.md)) or for Haiku ([ADR 0015](../decisions/0015-reasoning-off-and-output-caps.md)), so runs may vary slightly.
- **Small held-out sets.** About 20 questions per corpus, so confidence intervals are wide ([ADR 0016](../decisions/0016-governance-and-release-gates.md)).
- **Dev gold set reviewed by Claude, not the owner** ([ADR 0020](../decisions/0020-dev-gold-set-reviewed-by-claude.md)). Dev scores are measured against a Claude-reviewed key. Same-model drafting risk is recorded in [ADR 0018](../decisions/0018-gold-set-drafting.md).
- **Snapshot currency.** FY2025 or FY2026 filings and the 2023 handbook edition only.
- **Single instance.** Rate limits and spend cap live in memory and reset on restart ([ADR 0023](../decisions/0023-pre-deploy-security-review.md)).
- **Not measured yet.** The dev baseline, injection runs and calibration have not been completed as of the control matrix draft ([control matrix](control-matrix.md)). `TODO(owner)`: update this line when they have.
- **Bias, harmful content, environmental impact.** Not assessed. See the gaps in [nist-crosswalk.md](nist-crosswalk.md).

## 8. Human oversight

See [human-oversight.md](human-oversight.md). Summary: people review the gold sets and judge calibration, answers carry checkable citations, and an AI notice is planned for the live demo.

## 9. Contact

`TODO(owner)`: the contact route (GitHub issues, or the contact on the portfolio site). Security reports go through GitHub private vulnerability reporting ([SECURITY.md](../../SECURITY.md)). Incidents: [incident-response.md](incident-response.md).
