# Architecture Decision Records

One short file per significant decision, numbered in order (`0001-short-title.md`). Write a record when the decision changes the system's shape or would be costly to reverse. Skip small choices.

A record is never edited after the fact. If a decision changes, write a new record that supersedes the old one, and update the old record's status.

## Template

```markdown
# NNNN. Title

- **Status:** Proposed | Accepted | Superseded by NNNN
- **Date:** YYYY-MM-DD

## Context
The problem and the constraints that matter here.

## Options considered
- **Option A**: pros / cons
- **Option B**: pros / cons

## Decision
What we chose.

## Why
The reasoning, including what we're trading away.

## Consequences
What this makes easier or harder later, and what would make us revisit it.
```

## Index
| # | Decision | Status |
|---|----------|--------|
| [0001](0001-hand-rolled-retrieval.md) | Write our own retrieval pipeline (no LangChain/LlamaIndex) | Accepted |
| [0002](0002-openrouter-for-all-model-calls.md) | Route all model calls through OpenRouter | Accepted |
| [0003](0003-docker-local-and-live-demo.md) | Docker Compose locally; replay first, then a capped live demo | Accepted |
| [0004](0004-corpora-10k-and-faa-handbook.md) | Corpora: SEC 10-Ks and the FAA Pilot's Handbook | Accepted |
