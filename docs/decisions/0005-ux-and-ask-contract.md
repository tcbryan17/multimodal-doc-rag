# 0005. User experience and the `/ask` contract

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The kinds of question we support decide what retrieval, chunking and the API need to do. The `/ask` response is also a contract with the portfolio site, which replays a saved response (`replay/sample-run.json`). The site has no backend.

## Options considered
**Question types for v1**
- **Fact lookup** ("What was Apple's R&D spend?"). One passage or table row holds the answer.
- **Reading a figure** ("Using the takeoff chart, how far at 30°C?"). The answer exists only in an image.
- **Explaining a concept** ("How does an attitude indicator work?"). Text and a diagram across several chunks.
- **Comparing documents** ("Compare Apple and Microsoft R&D growth"). Needs evidence from several documents in one answer, which means per-document retrieval or query decomposition.

**What a figure answer shows**
- **Citation only** (`doc`, `page`, `snippet`). Simple, but the user can't see the chart the answer came from.
- **The figure itself.** The user can check the answer, and it's the most convincing demo. It needs stored figure crops and an image field in the contract.

**Search scope**
- **Pick a corpus first.** Simpler and more precise, but less impressive.
- **Always search everything.** A question about Apple can pull in Microsoft passages.
- **Everything by default, with an optional filter.**

**Page reference in citations**
- **File page index (`int`).** Simple, but "page 87" means nothing to someone holding the printed handbook.
- **Printed page label (`str`).** What the reader sees on the page, e.g. "4-12" in the handbook or "37" in a 10-K.

## Decision
- v1 supports **fact lookup, reading a figure and explaining a concept**. Cross-document comparison is a stretch goal.
- Figure answers **show the figure**.
- Search covers **everything by default, with an optional corpus or document filter**.
- Citations show the **printed page label** and an optional end page for chunks that span a page break.

The contract becomes:
```
POST /ask   { "question": str, "corpus"?: str, "doc"?: str }
→ { "answer": str,
    "citations": [{ "doc": str, "page": str, "page_end"?: str,
                    "snippet": str, "image_url"?: str }],
    "trace": [{ "step": str, "detail": str, "ms": int }] }
```
`image_url` points to `GET /figures/{id}.png` on the live API. In the replay file it's a `data:image/png;base64,…` URI, because the static site has no backend to serve it.

## Why
Comparison questions are the hardest retrieval problem and would add a query-planning step. Leaving them out keeps v1 focused on the multimodal story. Showing the figure turns "trust me" into "see for yourself". Printed labels are how people actually cite these documents.

## Consequences
- Chunks must carry corpus and document metadata that can be filtered on.
- Labels are text, so they can't be compared or sorted reliably ("4-9" sorts after "4-12"). Chunks therefore store both an integer page index (for range checks and recall@5) and the printed label (for display). See 0010.
- Figure crops must be stored and served. See 0008 and 0010.
- Changing the contract means updating the README, the portfolio site and the replay file together.
