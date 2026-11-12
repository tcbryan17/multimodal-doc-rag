# Control matrix

Each control the system relies on: the risk it addresses, where code enforces it, and the test or report that proves it. This is part of the governance set in [ADR 0016](../decisions/0016-governance-and-release-gates.md). Risks are described in the [risk register](risk-register.md).

- **Status:** *draft for owner review* (2026-11-11). Written before the dev baseline; the "Evidence" column gets eval and injection reports once they exist.
- **Frameworks:** the [OWASP Top 10 for LLM Applications 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) (names and numbers checked against the official PDF on 2026-11-11), and the four NIST AI RMF functions: Govern, Map, Measure, Manage.
- **Rule:** *implemented* means the code exists **and** a test or committed report proves it. A control that only exists as a plan is *planned*, even if it is easy to add. No deployment control is implemented, because nothing is deployed yet (ADR 0016).

Test paths are under `tests/`; `file.py::name` means a test function in that file.

## 1. Prompt injection and untrusted content

| # | Control | OWASP 2026 | NIST | Enforced in | Proven by | Status |
|---|---|---|---|---|---|---|
| C1 | Retrieved passages are wrapped in numbered `<source>` delimiters, and any `<source` / `</source` inside a passage is neutralised, so retrieved text can't close its fence early | LLM01 Prompt Injection | Manage | `answer.py` (`build_messages`) | `test_answer.py::test_sources_are_numbered_and_delimited`, `test_model_adapters.py::test_generator_sends_delimited_sources_and_image_and_parses_citations` | implemented |
| C2 | The system prompt says sources are untrusted data, never instructions, and to ignore requests to reveal or change its rules | LLM01, LLM08 Hidden Context Exposure | Manage | `answer.py` (`SYSTEM_PROMPT`, rules 5–6) | `test_answer.py::test_system_prompt_has_the_key_rules` | implemented (effectiveness measured by C4) |
| C3 | The eval judge's inputs are fenced the same way, and it is told that text trying to instruct it is evidence, not an instruction | LLM01 | Measure | `evals/judge.py` (`JUDGE_SYSTEM`, `_fence`) | `test_evals_judge.py::test_prompt_fences_untrusted_text_and_neutralises_closing_tags` | implemented |
| C4 | Injection test sets: 15 direct attacks against `rag`, 8 indirect attacks planted in a synthetic poisoned chapter that exists only in `rag_eval`. Each has a canary that appears only if the attack worked. Release gate: canary rate ≤ 0 | LLM01, LLM05 Data and Model Poisoning, LLM09 Vector and Embedding Weaknesses | Measure | `evals/injection/`, `evals/poisoned/`, `scripts/make_eval_index.py`, `evals/gates.py` (`injection_canary`) | `test_evals_injection_and_index.py` (canaries not spelled out; poisoned PDF ingests and is retrieved), `test_evals_runner.py::test_injection_canary_and_reach` | tooling implemented; **the sets are drafts and have never run** |
| C5 | An indirect attack counts only if its poisoned text actually reached the generator; the release check needs at least 5 that did | LLM01, LLM09 | Measure | `evals/gates.py` (`injection_problems`) | `test_evals_gates.py::test_release_check_rejects_an_indirect_run_that_tested_nothing`, `::test_release_check_blocks_on_thin_or_errored_injection_evidence` | implemented |
| C6 | The poisoned document never enters the product index: the eval index is a separate database, and the tool refuses to target the source | LLM05, LLM09 | Manage | `evals/index.py` (`check_create_allowed`) | `test_evals_injection_and_index.py::test_create_refuses_to_target_the_source`, `::test_create_refuses_existing_target_without_recreate` | implemented |

## 2. Grounding and misinformation

| # | Control | OWASP 2026 | NIST | Enforced in | Proven by | Status |
|---|---|---|---|---|---|---|
| C7 | Citations are checked, not trusted: a marker pointing outside the retrieved passages is dropped, and only ids the pipeline handed the model can come back | LLM07 Misinformation, LLM10 Improper Output Handling | Manage | `answer.py` (marker parsing and renumbering), `pipeline.py` | `test_answer.py::test_out_of_range_markers_are_dropped`, `::test_renumbering_drops_markers_that_cite_nothing`, `test_pipeline.py::test_unknown_cited_ids_are_ignored`, `test_model_adapters.py::test_generator_drops_invalid_markers` | implemented |
| C8 | Nothing retrieved means a fixed "I don't know" with no model call, so there is nothing for the model to make up an answer from | LLM07 | Manage | `pipeline.py` | `test_pipeline.py::test_empty_db_returns_idk_without_calling_generator`, `contracts/test_generator_contract.py::test_no_passages_means_i_dont_know_and_no_citations` | implemented |
| C9 | Every citation carries the printed page label (and the figure image), so a reader can check the claim against the source | LLM07 | Manage | `pipeline.py`, `api.py` (`/figures/{id}.png`) | `test_end_to_end.py::test_ask_returns_cited_answer_with_printed_page_label`, `test_end_to_end_figures.py::test_figure_question_cites_a_fetchable_image_on_the_printed_page` | implemented |
| C10 | Quality is gated before release: recall@5, citation accuracy, faithfulness, correctness, false abstention and abstention, pre-registered in `gates.toml` and checked on the held-out run only | LLM07 | Measure | `evals/gates.toml`, `evals/gates.py`, `scripts/release_check.py` | `test_evals_gates.py` (pins the thresholds and the binding rules) | tooling implemented; **no eval has run** |
| C11 | The judge is from a different model family from the generator, sees the same figure images the generator saw, and is calibrated against the owner's hand grades (kappa ≥ 0.6) | LLM07 | Measure | `evals/judge.py` (`check_judge_config`), `evals/runner.py`, `evals/calibration.py` | `test_evals_judge.py::test_same_family_as_generator_is_refused`, `::test_judge_is_shown_each_figure_image_right_after_its_passage`, `test_evals_calibration.py` | tooling implemented; **not calibrated yet** |
| C12 | The calibration must be of the judge that scored the final run: grades record the judge's fingerprint (model + output cap + prompt), and the release check blocks on a mismatch (ADR 0019) | LLM07 | Measure | `evals/judge.py` (`judge_fingerprint`), `evals/gates.py` (`calibration_problems`) | `test_evals_judge.py::test_judge_fingerprint_names_model_cap_and_prompt`, `test_evals_gates.py::test_release_check_blocks_when_calibration_graded_a_different_judge` | implemented |
| C13 | Figure failures degrade visibly: a failed vision description keeps the caption, is recorded in `ingest_failures`, and counts against the figure-coverage gate (≥ 99%) | LLM07 | Manage, Measure | `ingest.py`, `evals/gates.py` (`figure_coverage`) | `test_ingest.py::test_describer_exception_degrades_and_records_failures`, `test_corpus_ingest_db.py::test_degraded_figures_are_counted_and_listed`, `test_evals_gates.py::test_figure_coverage_counts`; the retry reports in `reports/ingest/` (3 of 496 figures still caption-only after the last retry, `20261109T165409Z-retry-failures.md`) | implemented |
| C14 | A truncated model reply is named (`finish_reason`), not silently used; hidden reasoning is off so it can't eat the output cap | LLM07 | Manage | `models/openrouter.py`, `models/` adapters (ADR 0015) | `test_openrouter_client.py::test_chat_reports_finish_reason_and_truncation`, `test_model_adapters.py::test_describer_names_a_truncated_reply` | implemented |
| C15 | "Answers are generated by AI" notice in the UI (EU AI Act Art. 50), beside the existing "not financial, legal, or flight-training advice" disclaimer | LLM07 | Govern | the portfolio site / UI | none yet | **planned** (deployment) |

## 3. Privacy and sensitive information

| # | Control | OWASP 2026 | NIST | Enforced in | Proven by | Status |
|---|---|---|---|---|---|---|
| C16 | Every OpenRouter request demands zero data retention and no data collection (`provider: {zdr: true, data_collection: "deny"}`), set in the one client every model call goes through | LLM02 Sensitive Information Disclosure | Govern, Manage | `models/openrouter.py` (`PRIVACY_PROVIDER`) | `test_openrouter_client.py::test_every_request_demands_zdr_and_no_data_collection`, `test_model_adapters.py::test_dimensions_param_is_sent_and_zdr_fields_present`, `test_evals_judge.py::test_real_judge_grades_via_chat_with_the_judge_model`, `test_live_openrouter.py::test_live_chat_with_image_part_under_zdr` (live only) | implemented |
| C17 | The API key is a `SecretStr`, never logged, never echoed in errors; a provider failure answers 502 with a fixed message | LLM02 | Manage | `config.py`, `models/openrouter.py`, `api.py` | `test_config.py::test_real_key_is_kept_secret`, `test_openrouter_client.py::test_headers_and_key_not_leaked`, `test_ask_contract.py::test_model_provider_failure_returns_502_not_500` | implemented |
| C18 | Public documents only; no personal data in the corpus | LLM02 | Map | `scripts/fetch_corpus.py` (fixed source list) | [data card](data-card.md) | implemented |
| C19 | The system prompt holds nothing secret, so leaking it costs nothing | LLM08 Hidden Context Exposure | Map | `answer.py` (the prompt is in the public repo) | the repository itself | implemented |
| C20 | A policy for live questions: whether to log them, for how long, and with no personal data in logs | LLM02 | Govern | not built | none | **planned** (deployment decision) |

## 4. Cost, consumption and availability

| # | Control | OWASP 2026 | NIST | Enforced in | Proven by | Status |
|---|---|---|---|---|---|---|
| C21 | A fail-closed spending cap on every offline run (ingest, drafting, eval): the client charges a shared `CostMeter`, which stops before overspending, and an unknown price is charged a pessimistic flat rate | LLM06 Unbounded Consumption | Manage | `models/cost.py`, `models/openrouter.py` | `test_cost.py` (e.g. `test_check_raises_once_cap_reached`, `test_client_charges_meter_and_stops_before_overspending`, `test_unknown_price_charges_the_pessimistic_flat_rate`), `test_evals_runner.py::test_run_eval_stops_on_the_cap_and_marks_the_report_partial`, `test_corpus_ingest_db.py::test_budget_exhaustion_rolls_back_current_document_and_marks_the_rest` | implemented |
| C22 | The OpenRouter key is project-only, with a $5 credit limit set at the provider | LLM06 | Govern | OpenRouter account (outside the code) | CLAUDE.md, ADR 0002 | implemented (not testable in code) |
| C23 | Input cap: `/ask` questions are 1–1,000 characters; unknown fields are rejected | LLM06, LLM01 | Manage | `contracts.py` (`MAX_QUESTION_LENGTH`) | `test_ask_contract.py::test_bad_question_returns_422`, `::test_max_length_question_accepted`, `::test_unknown_field_returns_422` | implemented |
| C24 | Output cap: answers are capped at 1,200 tokens, figure descriptions at 3,000 | LLM06 | Manage | `api.py` (`MAX_ANSWER_TOKENS`), adapters (ADR 0015) | `test_model_adapters.py::test_describer_turns_reasoning_off_by_default` (caps are constants; no test asserts their values) | implemented (weak evidence) |
| C25 | Release gate on mean cost per question (≤ $0.005) and p95 latency (≤ 8 s) | LLM06 | Measure | `evals/gates.toml` | `test_evals_gates.py::test_cost_and_latency_gates_skip_errored_items` | tooling implemented; **not measured yet** |
| C26 | Per-IP rate limits and a daily spend cap on the live `/ask` (the offline `CostMeter` does not cover the API) | LLM06 | Manage | not built | none | **planned** (deployment) |
| C27 | Monitoring: cost per day, error rate, "I don't know" rate; an incident response note | LLM06, LLM07 | Manage | not built | none | **planned** (deployment) |
| C28 | Provider resilience: retry on 429; reranker failure falls back to hybrid order; `/ask` answers 503 with no key and 502 on provider failure, never 500 | LLM06 | Manage | `models/openrouter.py`, `pipeline.py`, `api.py` | `test_openrouter_client.py::test_retry_on_429_then_success`, `test_pipeline.py::test_rerank_failure_falls_back_to_hybrid_order`, `test_ask_contract.py::test_no_key_answers_503_without_touching_the_database` | implemented |

## 5. Agency, output handling and supply chain

| # | Control | OWASP 2026 | NIST | Enforced in | Proven by | Status |
|---|---|---|---|---|---|---|
| C29 | No agency: the model has no tools and takes no actions. It only returns text, which the pipeline parses | LLM03 Excessive Agency | Map | architecture (ADR 0001) | `pipeline.py` has no tool calls; the trace has four fixed steps (`test_pipeline.py::test_trace_has_four_timed_steps`) | implemented |
| C30 | Model output is data in a typed response (Pydantic), never executed or used as SQL; database queries are parameterised | LLM10 Improper Output Handling | Manage | `contracts.py`, `search.py`, `db/repository.py` | Typed response: `test_ask_contract.py::test_exact_shape_optional_fields_absent`. Parameterised SQL (values as `%s` parameters; query pieces composed with psycopg's `sql.SQL` / `sql.Literal`, never f-strings): code review only, no test targets it; `test_evals_injection_and_index.py::test_statements_quote_identifiers` covers the eval-DB create/drop statements | implemented (SQL part: weak evidence). The UI must render answers as text, not HTML: **planned** (deployment) |
| C31 | Read-only database role for the API; non-root container | LLM10, LLM06 | Manage | not built | none | **planned** (deployment) |
| C32 | Dependencies pinned in `uv.lock`; CI runs lint, strict types and tests on every push; model calls go through our own thin client, not a provider SDK | LLM04 Supply Chain | Govern | `uv.lock`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml` (ADR 0002, 0012) | `ci.yml` runs on every push and pull request: `uv sync --locked`, ruff check, ruff format check, strict mypy, pytest (with a pgvector service container) | implemented |
| C33 | Source documents come only from sec.gov and faa.gov by script, with SHA-256 recorded and an identical re-ingest a no-op | LLM04, LLM05 | Map | `scripts/fetch_corpus.py`, `fetch.py`, `documents.sha256 UNIQUE` | `test_fetch.py`, `test_corpus_ingest_db.py::test_rerun_skips_existing_without_spending`, [data card](data-card.md) | implemented |

## 6. Release governance

| # | Control | OWASP 2026 | NIST | Enforced in | Proven by | Status |
|---|---|---|---|---|---|---|
| C34 | Gates pre-registered before any score existed, pinned by a test, frozen once the dev baseline exists | all | Govern | `evals/gates.toml` | `test_evals_gates.py::test_committed_gates_are_the_pre_registered_ones`, `::test_committed_evidence_minimums_are_the_pre_registered_ones` | implemented |
| C35 | The held-out split is scored once, deliberately: the runner refuses without `--i-know-this-is-heldout`, and a gold item's split must match its document's | all | Measure | `scripts/run_eval.py`, `evals/gold.py` | `test_evals_runner.py::test_heldout_needs_an_explicit_acknowledgement`, `test_evals_gold.py::test_split_must_match_manifest`, `test_evals_draft_review.py::test_verify_checks_split_against_manifest` | implemented |
| C36 | Release needs every gate to pass on enough evidence from one system; missing evidence blocks | all | Manage | `scripts/release_check.py`, `evals/gates.py` | `test_evals_gates.py` (`test_release_check_*`) | tooling implemented; **never run on real evidence** |
| C37 | Deployment runs `release_check.py` as a required CI step and refuses to ship on a non-zero exit | all | Manage | not built | none | **planned** (deployment) |

## Gaps this matrix shows

- **Nothing is measured yet.** C4, C10, C11 and C25 exist as tooling only. Their evidence column fills in with the dev baseline, the injection runs and the calibration (build plan steps 15 and 17).
- **The live API has no spend cap or rate limit** (C26). The offline `CostMeter` protects ingest and eval runs, not `/ask`. Until C26 exists, the only limit on live spending is the provider credit limit (C22).
- **Two controls rest on code review, not tests:** the output caps (C24 asserts no values) and parameterised SQL in search and the repository (C30). A small test for each would make them stronger.
