# Concept map

These are the ideas this project is built on. Toby owns them. He has to understand each one and defend it in an interview, so each has a study guide here.

The rule for agents: write boilerplate only, and never rewrite concept code. Any new concept code starts as a `TODO(human)` stub that lists the options and trade-offs. Toby chooses and types the real thing. Each guide ends with interview questions and a blank `**Your answer:**` line. Toby fills those in himself.

A guide marked "gap: stub" covers a concept where the repo is missing something. An agent has left a stub file in the repo for it. The stub is not the answer, it is a place to start.

## Boundary

Agents may own these boilerplate areas:

- `src/multimodal_doc_rag/api.py`, `ratelimit.py`, `stats.py`, `config.py`
- `src/multimodal_doc_rag/models/openrouter.py`: the transport. The ZDR provider rule (`PRIVACY_PROVIDER`) is a privacy decision (ADR 0009) and stays with Toby.
- `src/multimodal_doc_rag/db/`
- `src/multimodal_doc_rag/fetch.py`, `corpus_ingest.py`, `ingest.py`
- `scripts/`
- `src/multimodal_doc_rag/evals/`: the runner, report, results, wiring, index, chunk_index, draft and review modules
- `src/multimodal_doc_rag/replay.py`, `contracts.py`, `fakes.py`, `protocols.py`
- `tests/`
- `Dockerfile`, `fly.toml`, `.github/`

Everything else is concept code and belongs to Toby. The guides below point at it.

Model usage for agent work: Sonnet for implementation, Opus for review.

## Index

| # | Concept | Guide | Main code | ADRs | Status |
|---|---|---|---|---|---|
| 1 | Parsing and figure regions | [01-parsing.md](01-parsing.md) | `parsing/handbook_pdf.py`, `parsing/edgar.py` | 0006 | built |
| 2 | Chunking | [02-chunking.md](02-chunking.md) | `chunking.py` | 0007 | built |
| 3 | Context header and embed text | [03-context-header.md](03-context-header.md) | `chunking.py`, `types.py` | 0007, 0017 | built |
| 4 | Embedding | [04-embedding.md](04-embedding.md) | `models/adapters.py`, `models/vectors.py` | 0009 | built |
| 5 | Lexical and vector search | [05-lexical-and-vector-search.md](05-lexical-and-vector-search.md) | `search.py`, `migrations/0001_init.sql` | 0010 | built |
| 6 | Fusion (RRF) | [06-fusion.md](06-fusion.md) | `search.py` | 0010 | built |
| 7 | Reranking | [07-reranking.md](07-reranking.md) | `pipeline.py`, `models/adapters.py` | 0009 | built |
| 8 | Multimodal figures | [08-multimodal-figures.md](08-multimodal-figures.md) | `ingest.py`, `models/adapters.py`, `search.py` | 0008, 0015 | built |
| 9 | Prompt, citations and refusal | [09-prompt-citations-refusal.md](09-prompt-citations-refusal.md) | `answer.py`, `pipeline.py` | 0005, 0011 | built, gap: refusal is prompt-only (stub `refusal.py`) |
| 10 | Retrieval metrics | [10-retrieval-metrics.md](10-retrieval-metrics.md) | `evals/metrics.py` | 0011 | built, gap: no rank-aware metric (stub `rank_metrics.py`) |
| 11 | Answer metrics and the LLM judge | [11-answer-metrics-and-judge.md](11-answer-metrics-and-judge.md) | `evals/metrics.py`, `evals/judge.py` | 0011, 0014 | built |
| 12 | Judge calibration | [12-judge-calibration.md](12-judge-calibration.md) | `evals/calibration.py` | 0016, 0019 | built, gap: no kappa CI or weighted kappa (stub `agreement_stats.py`) |
| 13 | Release gates and cost guardrails | [13-release-gates-and-cost.md](13-release-gates-and-cost.md) | `evals/gates.toml`, `evals/gates.py`, `models/cost.py`, `spend.py` | 0016, 0017 | built |

## The three gap stubs

- `src/multimodal_doc_rag/refusal.py::decide_refusal`: a refusal policy that does not depend on the model obeying the prompt. See guide 9.
- `src/multimodal_doc_rag/evals/rank_metrics.py::reciprocal_rank` and `src/multimodal_doc_rag/evals/rank_metrics.py::ndcg_at_k`: MRR and nDCG, which recall@5 cannot give. See guide 10.
- `src/multimodal_doc_rag/evals/agreement_stats.py::kappa_bootstrap_ci` and `src/multimodal_doc_rag/evals/agreement_stats.py::weighted_kappa`: a confidence interval for kappa, and a kappa that respects the 0 / 0.5 / 1 order. See guide 12.

## Checking the links

`tests/test_concept_links.py` reads every guide. It checks that each code reference points at a real file and symbol, and that each guide has all six sections. If you rename a function, that test tells you which guide to update.
