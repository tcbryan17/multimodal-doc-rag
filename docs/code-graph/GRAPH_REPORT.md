# Graph Report - multimodal-doc-rag  (2026-11-14)

## Corpus Check
- Corpus is ~41,391 words - fits in a single context window. You may not need a graph.

## Summary
- 964 nodes · 2619 edges · 60 communities (44 shown, 16 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 310 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Eval Runner & Judge
- Corpus Fetching
- Judge Calibration
- Corpus Ingest Orchestration
- CLI Scripts & Shared Imports
- Gold-Set Review Loop
- Handbook PDF Layout
- Release Gates
- Core Types & Protocols
- Eval Reports & Results
- EDGAR HTML Parser
- FastAPI Endpoints
- Eval Metrics & CIs
- Embedding & Hybrid Search
- Component Wiring & Settings
- Gold-Set Storage
- Chunker
- Gold Drafting Prompts
- DB Repository
- Eval & Chunk Databases
- Figure Description Adapter
- Handbook Page Parsing
- Pipeline & /ask Contract
- Draft-Gold CLI
- OpenRouter Model Adapters
- Run-Eval CLI Options
- Draft Parsing
- OpenRouter HTTP Client
- Release-Check CLI
- Reranking & Citations
- Chunk-Size Index Builder
- Parsers & Fakes
- Replay Export
- Answer Generation
- Embedder & Preflight
- Fake Embedder & Reranker
- Cost Meter & Pipeline Setup
- Ingest Entry Points
- Vector & Keyword Search
- Initial SQL Schema
- FAA Link Scraper
- Document Ingest
- Migrations Runner
- Ingest Reports
- Generator Protocol & Fake
- Chat Client Seam
- Poisoned-Doc Injection Index
- Provider Error Handling
- Report File Naming
- Cost Recording
- Binding-Run Checks
- PDF Reading Order
- Preflight Report

## God Nodes (most connected - your core abstractions)
1. `Passage` - 41 edges
2. `GoldItem` - 40 edges
3. `OpenRouterClient` - 38 edges
4. `main()` - 33 edges
5. `Embedder` - 25 edges
6. `BudgetExceededError` - 23 edges
7. `CostMeter` - 23 edges
8. `Conn` - 23 edges
9. `ingest_document()` - 21 edges
10. `cmd_draft()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `main()` --uses--> `EvalReport`  [INFERRED]
  scripts/calibrate_judge.py → src/multimodal_doc_rag/evals/results.py
- `cmd_draft()` --uses--> `OpenRouterClient`  [INFERRED]
  scripts/draft_gold.py → src/multimodal_doc_rag/models/openrouter.py
- `cmd_add()` --uses--> `GoldError`  [INFERRED]
  scripts/draft_gold.py → src/multimodal_doc_rag/evals/gold.py
- `main()` --uses--> `OpenRouterEmbedder`  [INFERRED]
  scripts/embed_missing.py → src/multimodal_doc_rag/models/adapters.py
- `main()` --uses--> `BudgetExceededError`  [INFERRED]
  scripts/embed_missing.py → src/multimodal_doc_rag/models/cost.py

## Import Cycles
- None detected.

## Communities (60 total, 16 thin omitted)

### Community 0 - "Eval Runner & Judge"
Cohesion: 0.05
Nodes (31): GoldItem, InjectionItem, build_judge_messages(), check_judge_config(), FakeJudge, _fence(), Judge, judge_fingerprint() (+23 more)

### Community 1 - "Corpus Fetching"
Cohesion: 0.09
Nodes (23): main(), archive_url(), _by_key(), chapter_pdf_url(), display_name(), download(), fetch_edgar(), get_json() (+15 more)

### Community 2 - "Judge Calibration"
Cohesion: 0.10
Nodes (25): main(), agreement(), AgreementReport, CalibrationEntry, CalibrationError, cohens_kappa(), confusion(), DimensionAgreement (+17 more)

### Community 3 - "Corpus Ingest Orchestration"
Cohesion: 0.11
Nodes (20): analyze_document(), approx_image_tokens(), CostEstimate, CountingDescriber, DocResult, DocStats, DryRunReport, estimate_cost() (+12 more)

### Community 5 - "Gold-Set Review Loop"
Cohesion: 0.10
Nodes (12): edit_item(), format_pages(), owner_item(), parse_pages(), pending(), reject(), replace_item(), review_injection() (+4 more)

### Community 6 - "Handbook PDF Layout"
Cohesion: 0.11
Nodes (16): assign_owners(), _Block, _Caption, figure_candidates(), figure_region(), find_captions(), heading_level(), _in_furniture() (+8 more)

### Community 7 - "Release Gates"
Cohesion: 0.16
Nodes (18): calibration_problems(), check_calibration(), check_eval(), check_index(), check_injection(), EvidenceMinimums, _fmt(), Gate (+10 more)

### Community 8 - "Core Types & Protocols"
Cohesion: 0.13
Nodes (4): parser_for(), FigureDescriber, Parser, SourceInfo

### Community 9 - "Eval Reports & Results"
Cohesion: 0.16
Nodes (18): groupings(), result_metrics(), _cell(), _clip(), _cost_latency(), _failure_lines(), where(), failures() (+10 more)

### Community 10 - "EDGAR HTML Parser"
Cohesion: 0.16
Nodes (13): _Break, _footer_label(), _grid(), _is_bold(), _is_hidden(), _Line, _merge_row(), _norm() (+5 more)

### Community 11 - "FastAPI Endpoints"
Cohesion: 0.13
Nodes (7): _configure(), figure(), get_db_conn(), _get_pool(), health(), lifespan(), fetch_figure_pngs()

### Community 12 - "Eval Metrics & CIs"
Cohesion: 0.14
Nodes (13): _eval_value(), Distribution, distribution(), extract_numbers(), is_abstention(), mean_ci(), MeanCI, metric_table() (+5 more)

### Community 13 - "Embedding & Hybrid Search"
Cohesion: 0.12
Nodes (9): retry_failures(), RetryReport, RetryResult, embed_missing(), Embedder, fetch_passages(), hybrid_search(), rrf() (+1 more)

### Community 14 - "Component Wiring & Settings"
Cohesion: 0.13
Nodes (7): Settings, OpenRouterJudge, build_components(), build_meter(), EvalComponents, PassThroughReranker, Price

### Community 15 - "Gold-Set Storage"
Cohesion: 0.16
Nodes (10): check_splits(), _check_unique(), _dump_lines(), GoldError, _HasId, load_gold(), load_injection(), save_injection() (+2 more)

### Community 16 - "Chunker"
Cohesion: 0.15
Nodes (10): chunk_document(), emit(), flush(), context_header(), count_tokens(), _figure_content(), _hard_split(), _split_paragraph() (+2 more)

### Community 17 - "Gold Drafting Prompts"
Cohesion: 0.16
Nodes (9): build_answerable_messages(), build_unanswerable_messages(), exclude_used(), fetch_candidate_chunks(), _passage_block(), sample_sources(), SourceChunk, split_sources() (+1 more)

### Community 18 - "DB Repository"
Cohesion: 0.16
Nodes (11): count_missing_embeddings(), delete_document(), document_exists(), get_document_sha(), index_document(), insert_chunks(), insert_document(), insert_embeddings() (+3 more)

### Community 19 - "Eval & Chunk Databases"
Cohesion: 0.17
Nodes (8): create_chunk_database(), check_create_allowed(), create_eval_database(), create_statement(), drop_statement(), EvalIndexError, in_use_message(), with_db()

### Community 20 - "Figure Description Adapter"
Cohesion: 0.16
Nodes (6): CaptionFigureDescriber, default_query_instruction(), FigureDescriptionError, _parse_description(), truncate_and_normalize(), FigureDescription

### Community 21 - "Handbook Page Parsing"
Cohesion: 0.18
Nodes (6): HandbookPdfParser, flush(), path(), _repeated_image_xrefs(), Element, Figure

### Community 22 - "Pipeline & /ask Contract"
Cohesion: 0.25
Nodes (7): ask(), AskRequest, AskResponse, Pipeline, TraceStep, RagPipeline, mark()

### Community 23 - "Draft-Gold CLI"
Cohesion: 0.23
Nodes (10): cmd_add(), cmd_draft(), cmd_review(), cmd_review_injection(), _doc_splits(), main(), draftable_doc_keys(), merge_drafts() (+2 more)

### Community 24 - "OpenRouter Model Adapters"
Cohesion: 0.17
Nodes (6): _load_generator(), main(), OpenRouterFigureDescriber, OpenRouterGenerator, OpenRouterReranker, OpenRouterClient

### Community 25 - "Run-Eval CLI Options"
Cohesion: 0.16
Nodes (8): main(), chunk_db_name(), render_json(), index_stats(), OptionsError, RunOptions, validate_options(), generator_warning()

### Community 26 - "Draft Parsing"
Cohesion: 0.19
Nodes (7): draft_items(), DraftOutcome, DraftParseError, _first_json_object(), next_ids(), parse_answerable(), parse_unanswerable()

### Community 27 - "OpenRouter HTTP Client"
Cohesion: 0.18
Nodes (3): _error_message(), image_part(), OpenRouterError

### Community 28 - "Release-Check CLI"
Cohesion: 0.22
Nodes (8): _load(), main(), _rel(), figure_coverage_counts(), load_gates(), load_minimums(), _read(), utc_stamp()

### Community 29 - "Reranking & Citations"
Cohesion: 0.21
Nodes (7): renumber_markers(), replace(), Citation, _citation(), _label(), _snippet(), Reranker

### Community 30 - "Chunk-Size Index Builder"
Cohesion: 0.18
Nodes (7): build_chunk_index(), ChunkIndexError, ChunkIndexResult, load_stored_figures(), StoredDocument, StoredFigure, with_stored_descriptions()

### Community 31 - "Parsers & Fakes"
Cohesion: 0.24
Nodes (4): PlainTextParser, EdgarHtmlParser, PageRef, ParsedDocument

### Community 32 - "Replay Export"
Cohesion: 0.20
Nodes (4): decode_data_uri(), figure_chunk_ids(), inline_figures(), site_events()

### Community 33 - "Answer Generation"
Cohesion: 0.24
Nodes (5): build_messages(), _label(), _pages(), parse_citations(), _source_block()

### Community 34 - "Embedder & Preflight"
Cohesion: 0.21
Nodes (4): _cost_source(), _meter_state(), run_preflight(), OpenRouterEmbedder

### Community 35 - "Fake Embedder & Reranker"
Cohesion: 0.20
Nodes (3): HashingEmbedder, OverlapReranker, _words()

### Community 36 - "Cost Meter & Pipeline Setup"
Cohesion: 0.24
Nodes (4): main(), build_pipeline(), get_pipeline(), CostMeter

### Community 37 - "Ingest Entry Points"
Cohesion: 0.27
Nodes (8): main(), dry_run(), main(), _meter(), main(), default_parsers(), select_entries(), db_name()

### Community 38 - "Vector & Keyword Search"
Cohesion: 0.22
Nodes (4): _filters(), keyword_search(), vector_search(), vector_search_query()

### Community 39 - "Initial SQL Schema"
Cohesion: 0.38
Nodes (9): chunks, chunks_document_id_idx, chunks_tsv_idx, documents, embeddings, embeddings_openai_3_small_1536_hnsw, embeddings_qwen3_8b_1024_hnsw, figures (+1 more)

### Community 40 - "FAA Link Scraper"
Cohesion: 0.22
Nodes (3): _AnchorCollector, ChapterLink, faa_chapter_links()

### Community 43 - "Ingest Reports"
Cohesion: 0.32
Nodes (3): _save(), Report, write_report()

### Community 44 - "Generator Protocol & Fake"
Cohesion: 0.38
Nodes (3): EchoGenerator, Generator, GeneratedAnswer

### Community 48 - "Report File Naming"
Cohesion: 0.40
Nodes (3): report_basename(), report_paths(), slug()

### Community 51 - "PDF Reading Order"
Cohesion: 0.67
Nodes (3): reading_order(), is_full(), key()

## Knowledge Gaps
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Passage` connect `Eval Runner & Judge` to `Answer Generation`, `Core Types & Protocols`, `Eval Reports & Results`, `Eval Metrics & CIs`, `Generator Protocol & Fake`, `Component Wiring & Settings`, `Embedding & Hybrid Search`, `Figure Description Adapter`, `Pipeline & /ask Contract`, `OpenRouter Model Adapters`, `Reranking & Citations`, `Parsers & Fakes`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Are the 21 inferred relationships involving `Passage` (e.g. with `build_messages()` and `_pages()`) actually correct?**
  _`Passage` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Should `Eval Runner & Judge` be split into smaller, more focused modules?**
  _Cohesion score 0.050286058416139714 - nodes in this community are weakly interconnected._
- **Why does `GoldItem` connect `Eval Runner & Judge` to `Gold-Set Review Loop`, `Eval Metrics & CIs`, `Component Wiring & Settings`, `Gold-Set Storage`, `Gold Drafting Prompts`, `Draft-Gold CLI`, `Run-Eval CLI Options`, `Draft Parsing`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `GoldItem` (e.g. with `main()` and `DraftOutcome`) actually correct?**
  _`GoldItem` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Should `Corpus Fetching` be split into smaller, more focused modules?**
  _Cohesion score 0.09408033826638477 - nodes in this community are weakly interconnected._
- **Why does `OpenRouterClient` connect `OpenRouter Model Adapters` to `Eval Runner & Judge`, `Embedder & Preflight`, `Corpus Ingest Orchestration`, `Cost Meter & Pipeline Setup`, `Ingest Entry Points`, `Core Types & Protocols`, `FastAPI Endpoints`, `Component Wiring & Settings`, `Figure Description Adapter`, `Draft-Gold CLI`, `OpenRouter HTTP Client`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._