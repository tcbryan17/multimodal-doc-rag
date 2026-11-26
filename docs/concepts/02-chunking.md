# 2. Chunking

## What it does
Chunking cuts the parsed elements into the units we embed, retrieve and cite. `chunk_document` walks the elements in order. Small text paragraphs in the same section are merged with a blank line until adding the next one would pass `max_tokens` (default 500). A section change always starts a new chunk. A paragraph over the budget is split at sentence boundaries by `_split_paragraph`, and a sentence with no boundary is cut every `max_tokens * 4` characters. A table is its own chunk. If it is too big, `_split_table` splits it by rows and repeats the header row and separator in every piece. A single row bigger than the budget is kept whole. Each figure is its own chunk. A chunk may span a page break and records the start and end page. Tokens are counted as the number of characters divided by 4, rounded up.

## Where it lives
- `src/multimodal_doc_rag/chunking.py::chunk_document`
- `src/multimodal_doc_rag/chunking.py::_split_paragraph`
- `src/multimodal_doc_rag/chunking.py::_split_table`
- `src/multimodal_doc_rag/chunking.py::_hard_split`
- `src/multimodal_doc_rag/chunking.py::count_tokens`
- `src/multimodal_doc_rag/types.py::Chunk`
- `src/multimodal_doc_rag/evals/chunk_index.py` (the 256 / 512 / 1024 comparison index builder, boilerplate)

## What was chosen and why
ADR 0007. Structure-aware splitting keeps each chunk about one thing, so overlap is mostly unnecessary. Tables stay whole with their header, because a fact lookup needs the column names. Chunks may cross a page break so that paragraphs stay whole, and citations then read as a range. Chunk size is a setting, not a constant, so the eval can decide it. The `chars / 4` count is an approximation on purpose: every model tokenises differently, so exactness would be false precision.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| Fixed-size windows with overlap | Cuts through tables and sentences | Unstructured text with no usable headings, or a quick baseline |
| Semantic chunking (split where embedding similarity drops) | Opaque, and costs extra embedding calls | Long, unstructured prose where headings are missing |
| Never cross a page | Print layout makes half-paragraphs | If citations had to be to exactly one page and a slightly worse recall was acceptable |
| Fix a chunk size now | No evidence for any number | When the eval has already settled it |

## Evidence
- Index stats from `evals/reports/20261115T141659Z-judge-smoke-figures.md`: 3,449 chunks, mean 973.5 characters, maximum 3,424 characters.
- Unit tests in `tests/test_chunking.py` pin the rules, including that no text is lost across random inputs.
- Not measured yet: whether 256, 512 or 1024 is best. The tooling exists (`scripts/make_chunk_index.py`, `run_eval.py --chunk-tokens N`), but no dev baseline has run. ADR 0017 notes that `ingest_corpus.py` has no chunk-size option, so a winner could not be applied without a re-ingest decision.

## Interview questions
1. Why structure-aware chunks instead of fixed windows with overlap? What do you lose?

**Your answer:**

2. A table is too big for one chunk. What does `_split_table` do, and why repeat the header row in every piece?

**Your answer:**

3. Chunks can span a page break. How does that change citations and the recall@5 check?

**Your answer:**

4. You count tokens as `chars / 4`. When would that bite you, and why is it acceptable here?

**Your answer:**

5. How will you choose the chunk size, and what result would make you keep 500?

**Your answer:**
