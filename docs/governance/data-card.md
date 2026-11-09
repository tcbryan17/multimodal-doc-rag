# Data card

What data the system uses, where it came from, the rules it's handled under, and what leaves this machine. This is the "datasheet for datasets" idea (Gebru et al.) applied to a RAG corpus. It's part of the governance set in ADR 0016.

- **Last updated:** 2026-11-09, after the real ingest (step 14).
- **Evidence:** `data/manifest.json` (written by `scripts/fetch_corpus.py`; local, because `data/` is gitignored), the committed ingest reports in `reports/ingest/`, and the database.

## 1. Sources and provenance

25 source files in two corpora (ADR 0004, ADR 0013). Every file is fetched by a script, never by hand. Its SHA-256 is recorded at download time. `documents.sha256` is `UNIQUE` in the database, and re-ingesting an identical file does nothing.

| doc_key | Title | Split | Source | SHA-256 (first 12) |
|---|---|---|---|---|
| aapl-10k-2026 | Apple 10-K FY2026 | dev | [sec.gov](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm) | 8d258470509a |
| msft-10k-2026 | Microsoft 10-K FY2026 | dev | [sec.gov](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm) | 1f4b6bfe4008 |
| jnj-10k-2025 | Johnson & Johnson 10-K FY2025 | dev | [sec.gov](https://www.sec.gov/Archives/edgar/data/200406/000020040626000016/jnj-20251228.htm) | ee4ed3be87d3 |
| cost-10k-2026 | Costco 10-K FY2026 | **held-out** | [sec.gov](https://www.sec.gov/Archives/edgar/data/909832/000090983226000093/cost-20260830.htm) | f5d99bc31431 |
| phak-front | FAA-H-8083-25C, Front Matter | dev | [faa.gov](https://www.faa.gov/sites/faa.gov/files/01_phak_front.pdf) | 69fa639666f9 |
| phak-ch01 … ch10 | Ch. 1–10 | dev | faa.gov, one PDF per chapter | see manifest |
| phak-ch11 | Ch. 11: Aircraft Performance | **held-out** | [faa.gov](https://www.faa.gov/sites/faa.gov/files/13_phak_ch11.pdf) | 4b3c3ba37db7 |
| phak-ch12 | Ch. 12: Weather Theory | dev | [faa.gov](https://www.faa.gov/sites/faa.gov/files/14_phak_ch12.pdf) | 1df741210669 |
| phak-ch13 | Ch. 13: Aviation Weather Services | **held-out** | [faa.gov](https://www.faa.gov/sites/faa.gov/files/15_phak_ch13.pdf) | e71f7d50f83f |
| phak-ch14 | Ch. 14: Airport Operations | dev | [faa.gov](https://www.faa.gov/sites/faa.gov/files/16_phak_ch14_0.pdf) | 487e98510e45 |
| phak-ch15 | Ch. 15: Airspace | **held-out** | [faa.gov](https://www.faa.gov/sites/faa.gov/files/17_phak_ch15.pdf) | 153a7a515aac |
| phak-ch16, ch17 | Ch. 16–17 | dev | faa.gov | see manifest |
| phak-appendices, glossary, index | Back matter | dev | faa.gov | see manifest |

**Currency.** Each 10-K is a snapshot of one fiscal year (FY2025 for J&J, FY2026 for the others), and the handbook is the November 2023 edition (25C). Answers are only as current as these files. The system does not know about later filings or revisions.

## 2. Rights and terms of access

| Source | Status | How we comply |
|---|---|---|
| FAA *Pilot's Handbook of Aeronautical Knowledge* | A work of the US federal government, so not under copyright in the US (17 U.S.C. §105). | Fetched from faa.gov with an honest User-Agent (`multimodal-doc-rag/0.1`). Figures from it appear in the public replay. |
| SEC 10-K filings | Public filings on EDGAR. | SEC fair-access rules: a declared User-Agent with a real contact, and at most 10 requests per second. `fetch.py` refuses to make any SEC request without `SEC_USER_AGENT` and paces itself at about 5 per second. Tests: `test_missing_user_agent_raises_before_any_request`, `test_rate_limit_sleeps_between_sec_requests`. The contact lives only in the local `.env`. |

**Redistribution.** The source files are not committed (`data/` is gitignored), and anyone reproducing this fetches them from the original publishers. Answers quote short snippets with page citations. 10-Ks contain third-party trademarks; we refer to them, we don't republish them.

## 3. Personal and sensitive data

- **No private individuals' data** is collected or used. This is a hard rule in CLAUDE.md: public documents only.
- **Public-role personal data is present.** 10-Ks name executive officers and directors, with signatures, compensation references and biographies. That's public information disclosed by law. The system doesn't extract, aggregate or profile people. It answers questions about the documents.
- **The handbook** contains illustrative photographs and no personal records.
- **Live user questions** are the one place visitors could type personal data. There is no live endpoint yet. Whether questions are logged, and for how long, is an **open item for the deployment decision** (ADR 0016).

## 4. What leaves this machine

All model calls go through OpenRouter (ADR 0002). **Every** request sends `provider: {zdr: true, data_collection: "deny"}`, and ADR 0009 requires the OpenRouter account setting that allows only zero-data-retention endpoints. That makes two layers, so a mistake in either one alone can't leak data. The per-request layer is enforced in code and tested (`test_every_request_demands_zdr_and_no_data_collection`). The account layer is a dashboard setting: confirm it there, because no test can see it.

| When | What is sent | Purpose |
|---|---|---|
| Ingest | chunk text | embedding (`qwen/qwen3-embedding-8b`, 1,024 dims) |
| Ingest | figure images + captions | vision description (ADR 0008) |
| `/ask` | the question | embedding |
| `/ask` | question + candidate passages | reranking |
| `/ask` | question + top passages + figure images | answer generation |
| Eval only | question, reference, answer, passages | LLM judge (`openai/gpt-6-luna`, ZDR via Azure; ADR 0014) |

Every paid run sits under a fail-closed spending cap (`models/cost.py`). The API key is a `SecretStr` and never appears in logs.

## 5. Derived data (in Postgres)

Counts from the database on 2026-11-09:

| | 10-K | FAA | Total |
|---|---|---|---|
| documents | 4 | 21 | 25 |
| chunks | 1,399 | 2,050 | 3,449 |
| of which tables | 352 | 0 | 352 |
| of which figures | 0 | 496 | 496 |
| embeddings (`qwen/qwen3-embedding-8b@1024`) | | | 3,449 |

**Figures (ADR 0008):**
- 458 were described as informational.
- 35 were classified as decorative (ADR 0008's filter).
- **3 are caption-only.** The vision call still failed after the retries, and they keep only their caption: `phak-ch02#chunk28`, `#chunk57` and `#chunk76`.

That makes **figure coverage 493/496 = 99.4%**, which passes the 99% release gate. Evidence: `reports/ingest/20261109T162956Z-ingest.md` and the two `*-retry-failures.md` reports. The `ingest_failures` table keeps the history and stamps each fix with `resolved_at` rather than deleting it.

**Model-generated content.** Figure descriptions are written by a model and can be wrong. They're used to *find* figures. When answering, the generator receives the image itself, not just the description (ADR 0008), which limits the damage a bad description can do.

**Retention.** The local database is kept until `docker compose down -v`. Each embedding is keyed by its model, so changing the embedder adds rows instead of overwriting them.

## 6. Evaluation data

- **Splits.** The split is fixed per document in the manifest. Held-out: Costco and handbook chapters 11, 13 and 15 (ADR 0013). A gold item's split must match its documents' split, and both the runner and the drafter refuse a mismatch (`test_split_must_match_manifest`). Held-out scores are produced once, on purpose (`--i-know-this-is-heldout`).
- **Gold set.** A model drafts the questions, and the owner verifies **every** item and writes the figure questions personally (ADR 0011). Only `status: verified` items count.
- **Poisoned document.** A synthetic, deliberately malicious handbook chapter exists **only** in the eval database `rag_eval`, never in `rag` (ADR 0011).

## 7. Known gaps

- 3 caption-only figures (above).
- Snapshot currency (section 1).
- Logging of live queries is undecided until deployment (section 3).
- No PII scanner runs over the corpus. We rely on the source selection (public filings and a government handbook) instead.
