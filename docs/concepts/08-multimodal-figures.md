# 8. Multimodal figures

## What it does
Figures are handled in two separate steps: finding and reading. For finding, a vision model describes each figure once, at ingest. `ingest_document` calls the describer with the PNG, the caption and the context header, and the reply is one JSON object with `informational` (true or false) and a dense `description`. For an informational figure the description is put in front of the caption and becomes the chunk content, so it is embedded and is visible to keyword search. A decorative figure keeps only its printed caption, and no description is stored. For reading, the retrieved figure's PNG is fetched from the `figures` table by `fetch_figure_pngs` and sent to the generator next to its source block. A failed description does not stop the run: the chunk stays caption-only and the failure is recorded in `ingest_failures`, except a budget error, which stops everything. Hidden reasoning is off for descriptions, with a 3,000-token output cap.

## Where it lives
- `src/multimodal_doc_rag/ingest.py::ingest_document`
- `src/multimodal_doc_rag/models/adapters.py::DESCRIBE_PROMPT`
- `src/multimodal_doc_rag/models/adapters.py::OpenRouterFigureDescriber`
- `src/multimodal_doc_rag/models/adapters.py::FigureDescriptionError`
- `src/multimodal_doc_rag/search.py::fetch_figure_pngs`
- `src/multimodal_doc_rag/answer.py::build_messages`
- `src/multimodal_doc_rag/pipeline.py::RagPipeline.run`
- `migrations/0001_init.sql` (the `figures` table, `bytea`)

## What was chosen and why
ADR 0008. A description written at ingest can solve finding but not reading, because nobody knew then which value would be asked for. So the description is for retrieval and the image is for answering. Free rules drop tiny or repeated images. The same vision call that writes the description also says whether the figure is informational, so no separate classifier is paid for. Direct image embedding was planned as a comparison but the zero-retention rule ruled it out (ADR 0009). The comparison became "answer with the image against answer from the description only" (`run_eval.py --no-figure-images`). ADR 0015 then switched hidden reasoning off and raised the output cap from 700 to 3,000 after 139 of 496 descriptions (28%) were cut off.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| Embed the image directly with a multimodal embedder | Weaker on technical diagrams, invisible to keyword search, and the only zero-retention options are Gemini Embedding 2 (keeps inputs briefly) and Titan Image v1 (128 tokens) | If a zero-retention multimodal embedder appeared |
| Embed page screenshots (ColPali family) | Many vectors per page, hard to crop a figure for display, probably not on OpenRouter | A corpus of dense scanned pages with no text layer |
| Description only, no image to the generator | Cannot read a value off a chart unless the description happened to state it | If the eval showed the image adds nothing |
| Fail loudly on one bad figure | One bad image blocks a 500-page run | A tiny corpus |
| Skip failures silently | Coverage gaps go unnoticed | Never |
| Keep default reasoning, raise the cap | About twice the cost and latency for no extra detail (measured on four figures) | If the eval showed reasoning-on answers are clearly better |

## Evidence
- ADR 0015, four failed figures re-run with a 3,000-token cap: default reasoning 8.7 s and $0.00094, low effort 6.5 s and $0.00060, off 4.5 s and $0.00046, all four with complete JSON.
- First ingest (`reports/ingest/20261109T162956Z-ingest.md`): 496 FAA figures, 139 degraded. After the retry, 3 remained caption-only: 493 of 496 is 99.4%, above the 99% gate.
- Figure smoke run (`evals/reports/20261115T141659Z-judge-smoke-figures.md`): 3 questions, every metric 1.00, $0.0031 per question. That is only three questions.
- Not measured yet: the value of the image. Run the dev set with and without `--no-figure-images` and compare correctness on the 13 figure questions. Also not measured: reasoning on against off for answers (`--reasoning`).

## Interview questions
1. Why split "finding a figure" from "reading a figure"? What would break if you only stored a description?

**Your answer:**

2. How do you decide a figure is decorative, and what does a wrong call cost in each direction?

**Your answer:**

3. 28% of descriptions failed the first time. What was the cause, how did you find it, and what did you change?

**Your answer:**

4. Why can you not use a multimodal embedder here? What would you do if a private one appeared?

**Your answer:**

5. The generator and the judge both get the image. Why does the judge need it, and what would the faithfulness score look like if it did not?

**Your answer:**
