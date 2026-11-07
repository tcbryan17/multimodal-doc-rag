# 0001. Write our own retrieval pipeline (no LangChain or LlamaIndex)

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The pipeline has five steps: ingest, chunk, index, retrieve, answer. Frameworks such as LangChain and LlamaIndex package all of these behind ready-made abstractions. This is a portfolio project, so showing that we understand each step is part of the goal, not a side effect.

## Options considered
- **LangChain or LlamaIndex.** Pros: fast to a working demo, many integrations, and widely used in industry. Cons: the important logic hides behind framework classes, debugging means reading framework internals, the APIs change often, and it shows "can use the library" more than "understands retrieval".
- **Hand-rolled.** Pros: every step is visible, testable and explainable. We control chunk metadata (page numbers, section headers) end to end, which citations depend on. Fewer dependencies. The per-step `trace` in the API contract falls out naturally. Cons: more code to write, and we rebuild some things a framework gives for free, such as loaders and prompt templates.

## Decision
Hand-rolled. We'll use plain libraries for individual jobs (a PDF parser, a Postgres driver, an HTTP client for model APIs), but no orchestration framework.

## Why
In interviews, a candidate who can explain why hybrid search beats pure vector search, or how reranking changes recall@5, and point to the code that does it, stands out more than one who wired up framework components. Owning the chunk metadata also keeps citations accurate.

## Consequences
- More upfront code, so each module should stay small, have a clear interface, and be tested.
- Revisit if the pipeline grows features a framework solves well and that aren't core to the portfolio story, such as many document loaders.
