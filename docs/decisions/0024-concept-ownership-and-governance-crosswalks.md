# 0024. Concept ownership and governance crosswalks

- **Status:** Accepted
- **Date:** 2026-11-26
- **Builds on:** 0016 (governance and release gates). It does not supersede 0016. NIST AI RMF stays the anchor, and the rejection of an ISO/IEC 42001 management system stays.

## Context
This is a portfolio project, and the owner (Toby) has to defend every core idea in an interview. Agents have written a lot of the code, and some of it is concept code (chunking, search, fusion, prompts, metrics). The owner decided that agents write boilerplate only and Toby writes and owns the concepts. Existing concept code is never overwritten.

The review also found gaps where the repo has no code for an idea an interviewer would ask about: refusal beyond the prompt, a rank-aware retrieval metric, and agreement statistics beyond the raw gate.

On governance, ADR 0016 anchored on NIST AI RMF and the GenAI Profile. The owner works in Europe, so GDPR and ISO/IEC 42001 come up in interviews and in customer questions.

## Options considered

**For marking which code is the owner's**
- **(1) A concept map plus study guides, with a link-check test (chosen).** Zero source edits. A guide per concept points at the code and the ADRs.
- **(2) Comment markers in the code.** Visible where the code lives. Rejected: it edits many existing files and the markers go stale.
- **(3) A pre-commit hook that warns when concept files change.** Deferred. Add it later if agents drift.

**For the gaps**
- **(a) Agents write the missing code.** Fast, but the owner then explains code he did not write. Rejected.
- **(b) Do nothing.** The interview questions stay unanswerable. Rejected.
- **(c) `TODO(human)` stubs in new files only (chosen).** Each docstring lists the options and trade-offs. Contract tests are marked `xfail(raises=NotImplementedError, strict=True)`, so they pass as expected failures now and turn into a failure that demands attention once the owner writes the real code.

**For governance scope**
- **(x) Keep only NIST (0016).** Simple, but no map to the other frameworks people ask about.
- **(y) Add crosswalks and a GDPR note, adopt no new management system (chosen).** NIST subcategory tags with suggested AI 600-1 risks, an ISO/IEC 42001 crosswalk for awareness, a UK GDPR and EU GDPR note, and skeletons for the system card, incident response and human oversight.
- **(z) Adopt ISO/IEC 42001.** Rejected again: it is a certifiable management system, which is too heavy for a one-person demo (see 0016).

## Decision
- **Ownership.** `docs/concepts/` holds a concept map, 13 study guides and the boundary of what agents may touch. Each guide ends with interview questions and a blank answer line for the owner. `tests/test_concept_links.py` checks that the guides' links resolve.
- **Stubs.** Three new files, no existing file edited:
  - `src/multimodal_doc_rag/refusal.py`: refusal policy. Not wired into `pipeline.py` yet.
  - `src/multimodal_doc_rag/evals/rank_metrics.py`: MRR and nDCG@k. Reported only, not a gate.
  - `src/multimodal_doc_rag/evals/agreement_stats.py`: weighted kappa and a bootstrap confidence interval on kappa, reported beside the existing gate.
- **Gates.** `evals/gates.toml` is unchanged.
- **Governance.** NIST AI RMF stays the anchor. These drafts are added, all for owner review: `nist-crosswalk.md`, `iso42001-crosswalk.md`, `gdpr.md`, `system-card.md`, `incident-response.md`, `human-oversight.md`, and `frameworks-index.md`. The UK GDPR and Data Protection Act 2018 apply to the owner. The EU GDPR may apply to visitors in the EU.
- **Model usage for agent work.** Sonnet subagents implement, Opus reviews against tests and the plan, and Fable is used only for very important, wide-ranging problems.

## Why
The owner's understanding comes first (see `CLAUDE.md`). Guides and stubs make the boundary clear without touching working code. Crosswalks cost documents, not code, and answer the framework questions without taking on a management system.

## Consequences
- **Refusal.** The stub is not wired into `pipeline.py` until the owner writes it. Refusal affects the abstention gates, which freeze at the dev baseline, so it should be settled before the baseline (`docs/next-steps.md`).
- **Stubs stay xfail until written.** `strict=True` means a stub that starts to work unexpectedly fails the suite, so nobody forgets to remove the marker.
- **Interview answers stay blank** until the owner writes them.
- **Governance IDs need checking.** Framework identifiers (NIST subcategories, AI 600-1 risks, ISO clauses, GDPR articles) were written from memory and are flagged "check against source". The owner accepts or changes the NIST tags and the AI 600-1 suggestions.
- **GDPR open items:**
  - the deploy region;
  - data processing agreements (DPAs) with OpenRouter, Fly and Neon;
  - Fly and Neon log retention;
  - a privacy notice, which must ship with the AI notice (C15).
- **Revisit** the pre-commit hook (option 3) if agents start editing concept files, and revisit ISO/IEC 42001 only if a customer asks for it.
