# 3. Context header and embed text

## What it does
Each chunk carries a context header, built from the document title and the section path: `Apple 10-K FY2026 › Item 7 › Liquidity`. `context_header` joins them with " › ", or gives just the title if there is no path. The header is not stored inside `content`. It is a separate column. `embed_text` puts the header first and the content after a blank line, and that string is what gets embedded. The same header is also part of the generated `tsvector` column, so keyword search sees it too. The reranker and the generator receive `content` only, plus the document title and pages as attributes on the source block. Embedding always goes through the one function `embed_text`, so old and new vectors stay comparable.

## Where it lives
- `src/multimodal_doc_rag/chunking.py::context_header`
- `src/multimodal_doc_rag/types.py::embed_text`
- `src/multimodal_doc_rag/types.py::Chunk`
- `src/multimodal_doc_rag/db/repository.py::index_document`
- `migrations/0001_init.sql` (the `tsv` generated column)
- `src/multimodal_doc_rag/models/adapters.py::OpenRouterEmbedder`

## What was chosen and why
ADR 0007. A deterministic header is free and instant, and "It increased 12%" stops being anonymous once the chunk says which company, year and section it is from. ADR 0017 adds that the Qwen query instruction is applied only to models trained with one, so the embedder comparison is fair (see guide 4). The LLM-written header (Anthropic's "contextual retrieval") was kept as a later eval comparison, and ADR 0017 deferred it. It would cost one model call for each of about 3,450 chunks plus a fourth index.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| LLM-written header per chunk | One model call per chunk at index time, and the gain is unmeasured here. Deferred in ADR 0017. | If the eval showed weak retrieval that the deterministic header could not fix |
| No header, embed content only | Chunks lose where they came from | A corpus where every chunk is self-explanatory |
| Put the header inside `content` | The generator and reranker would read it too, and quoted snippets would carry it | If we wanted the generator to see the section path |

## Evidence
- `tests/test_chunking.py` checks the header format and that the title and section path appear.
- Not measured yet: how much the header helps recall@5. To measure it, build a second index that embeds `content` alone and run the same eval against both. The LLM-written header comparison is also not done.

## Interview questions
1. Why prepend a header before embedding rather than store more context in the text the user sees?

**Your answer:**

2. The header is also in the `tsvector`. What does that do to keyword search, good and bad?

**Your answer:**

3. Why does the reranker get `content` only? Would you change that?

**Your answer:**

4. What is "contextual retrieval", why did you defer it, and what would you need to see to bring it back?

**Your answer:**

5. Why is there exactly one definition of `embed_text`, and what breaks if the indexer and the re-embedder disagree?

**Your answer:**
