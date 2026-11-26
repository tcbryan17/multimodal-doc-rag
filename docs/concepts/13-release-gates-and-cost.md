# 13. Release gates and cost guardrails

## What it does
Eleven release gates are written in `evals/gates.toml`, and `evals/gates.py` turns evidence into pass, fail or not measured for each. Per corpus (10-K and FAA must each pass): recall@5 at least 0.80, citation accuracy at least 0.90, faithfulness at least 0.90, correctness at least 0.75, false abstention at most 0.10, mean answering cost at most $0.005 per question, and p95 latency at most 8,000 ms. Pooled: abstention on unanswerable questions at least 0.80, injection canary in answer exactly 0, judge kappa at least 0.60, and figure coverage at least 0.99. A gate passes on its point estimate. Missing evidence is "not measured" and blocks release. An `[evidence]` table sets minimum sample sizes (15 answerable held-out per corpus, 3 unanswerable, 25 hand grades, 12 direct attacks, 5 indirect attacks that reached the generator). Only the held-out final run binds, and `binding_problems` lists why a run cannot. Spending is capped by `CostMeter`: it charges the reported cost, else tokens times a price table, else a flat $0.005, and checks before each request. The live API uses `DailyCostMeter`, which resets each UTC day, defaulting to a $1.00 cap.

## Where it lives
- `evals/gates.toml`
- `src/multimodal_doc_rag/evals/gates.py::load_gates`
- `src/multimodal_doc_rag/evals/gates.py::check_eval`
- `src/multimodal_doc_rag/evals/gates.py::binding_problems`
- `src/multimodal_doc_rag/evals/gates.py::size_problems`
- `src/multimodal_doc_rag/evals/gates.py::injection_problems`
- `src/multimodal_doc_rag/evals/gates.py::release_ready`
- `src/multimodal_doc_rag/evals/gates.py::release_check`
- `src/multimodal_doc_rag/models/cost.py::CostMeter`
- `src/multimodal_doc_rag/models/cost.py::BudgetExceededError`
- `src/multimodal_doc_rag/spend.py::DailyCostMeter`
- `src/multimodal_doc_rag/config.py::Settings`

## What was chosen and why
ADR 0016: NIST AI RMF with the Generative AI Profile for structure, OWASP LLM Top 10 (2026) for security controls. The thresholds were committed on 2026-11-09, before the gold set existed or any eval ran, so they cannot drift to wherever the numbers land. They are the project's own bar, not industry standards. The held-out run binds because it is the only unbiased number. ADR 0017 added the evidence minimums, because a gate passing on four hand grades is half a criterion, and the "one system" rule that injection runs must match the final run's generator, reasoning, embedder, reranker, top-k and figure images. The cost meter fails closed on purpose: over-counting only stops a run early, under-counting could spend real money. Caps are $3.00 for ingest and $2.00 for eval, below the key's own $5 credit limit, so ours trips first.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| An ISO/IEC 42001 management system | Built for organisations. For one person it would be ceremony. | If a customer required certification |
| EU AI Act as the lead frame | Most of the Act does not apply to a non-high-risk demo | A product in a regulated use |
| Our own checklist | Cannot be compared with anything a reviewer knows | Never for a portfolio |
| Pre-register in docs only | Nothing enforces it | Never, here |
| Gate on the lower 95% CI bound | Near unpassable with about 20 held-out questions | A much larger held-out set |
| Dev run as the binding run | Dev is the tuned split, so optimistic | Never |
| Both dev and held-out must pass | Strictest, but not chosen | If dev and held-out were both large |
| Evidence minimums at exactly the planned sizes | One rejected question would force a replacement | If review rejected nothing |
| No minimums, report n | A threshold without a sample size is half a criterion | Exploration |
| A cap that sums reported costs only | Silently never trips when a response lacks a cost | Never |

## Evidence
- `tests/test_evals_gates.py` pins every threshold and minimum, so an edit cannot slip through unnoticed.
- `tests/test_cost.py` covers the three charging paths.
- Smoke run cost: $0.0112 over 12 calls for 3 figure questions, answering cost $0.0031 per question and p95 latency 4,035 ms (`evals/reports/20261115T141659Z-judge-smoke-figures.md`). Both are inside the cost and latency gates, on 3 questions.
- Figure coverage is 493 of 496, or 99.4% (`reports/ingest/20261109T165409Z-retry-failures.md` and `docs/governance/data-card.md`), above the 0.99 gate.
- First ingest spend: $0.1738 of the $3.00 cap over 562 calls.
- Not measured yet: every quality gate on held-out data. Held-out has 40 drafted items, all unreviewed. No dev baseline, no calibration and no injection run exists. `scripts/release_check.py` would currently exit non-zero.

## Interview questions
1. Why were the thresholds written before any eval ran? What would be wrong with picking 0.80 after seeing 0.83?

**Your answer:**

2. Why does missing evidence block release instead of counting as a pass or a skip?

**Your answer:**

3. With about 2 unanswerable held-out questions per corpus, why is the abstention gate pooled, and what is the cost of that choice?

**Your answer:**

4. Walk through what `CostMeter.record` does for a response with no `usage.cost`. Why charge a flat amount when the model is unknown?

**Your answer:**

5. The live daily cap lives in memory. Describe how an abuser could spend it more than once a day, and what bounds the damage.

**Your answer:**
