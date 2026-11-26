# 4. Embedding

## What it does
An embedder turns text into a vector so that similar meaning means a nearby vector. We use `qwen/qwen3-embedding-8b` through OpenRouter, cut to 1,024 dimensions. The model returns more dimensions than that, so `truncate_and_normalize` keeps the first 1,024 and rescales them to unit length. Qwen3 embeddings are trained so the most important information sits in the leading dimensions (Matryoshka training), so little is lost. Re-normalising matters because cosine distance assumes unit vectors. The adapter always truncates and normalises, even if the provider honoured the `dimensions` request, as a safety net. Queries get a task instruction in front ("Instruct: ... Query: ..."). Documents do not. Only models trained with that instruction get it. Each vector is stored under a model key such as `qwen/qwen3-embedding-8b@1024`.

## Where it lives
- `src/multimodal_doc_rag/models/adapters.py::OpenRouterEmbedder`
- `src/multimodal_doc_rag/models/adapters.py::default_query_instruction`
- `src/multimodal_doc_rag/models/adapters.py::DEFAULT_QUERY_TASK`
- `src/multimodal_doc_rag/models/vectors.py::truncate_and_normalize`
- `src/multimodal_doc_rag/models/openrouter.py::PRIVACY_PROVIDER`
- `src/multimodal_doc_rag/config.py::Settings`
- `migrations/0001_init.sql` (the `embeddings` table and one HNSW index per model)

## What was chosen and why
ADR 0009. The rule is strict zero data retention, enforced twice: an account setting, and a `provider: {zdr: true, data_collection: "deny"}` field on every request. Among zero-retention text embedders, qwen3-embedding-8b costs $0.01 per million tokens. The whole corpus is about 1M tokens, so price barely matters. The 1,024 limit exists because pgvector's HNSW index supports at most 2,000 dimensions for the `vector` type. The eval baseline is `openai/text-embedding-3-small` at 1,536 dimensions. Model IDs live in config, never in code.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| `openai/text-embedding-3-small` as the main embedder | Not rejected as a model: it is the eval baseline | If the eval shows Qwen no better, since it is simpler and on Azure |
| bge-m3 | Listed in ADR 0009 as a zero-retention option at $0.01 per million tokens. The ADR records no separate reason: Qwen3 was chosen, and the eval baseline is text-embedding-3-small. | If the eval showed it beat Qwen3 on our questions |
| Free NVIDIA Nemotron, Cohere embed-5, Voyage | No zero-retention endpoint (checked 2026-11-07) | If the privacy rule were relaxed |
| Direct image embedding (Gemini Embedding 2, Titan Image) | Gemini keeps inputs briefly for abuse checks, Titan is limited to 128 tokens | If a zero-retention multimodal embedder appears |
| Full-size vectors | HNSW limit of 2,000 dimensions | A different index type, or a smaller corpus where a sequential scan is fine |

## Evidence
- ADR 0009 price table (checked 2026-11-07). Embedding the whole corpus is cents.
- All 3,449 chunks have a 1,024-dimension vector (index line in `evals/reports/20261115T141659Z-judge-smoke-figures.md`).
- Not measured yet: Qwen3 at 1,024 against text-embedding-3-small at 1,536, and the cost in recall of truncating from the full size. `scripts/embed_missing.py` adds a second model's vectors to the same chunks, so the comparison needs no re-ingest. It has not been run, because there is no dev baseline yet.

## Interview questions
1. Why truncate to 1,024 dimensions and then re-normalise? What goes wrong if you skip the second step?

**Your answer:**

2. Why does the query get an instruction but the document does not? What happens to a model that was not trained with one?

**Your answer:**

3. What does "strict zero data retention" mean here, and why send the provider fields on every request as well as setting the account switch?

**Your answer:**

4. How would you compare two embedders fairly, and what could make the comparison unfair?

**Your answer:**

5. Embeddings are keyed by `model@dim`. Why, and what must you add to the database to serve a new embedder?

**Your answer:**
