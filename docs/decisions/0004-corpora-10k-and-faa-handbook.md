# 0004. Corpora: SEC 10-Ks and the FAA Pilot's Handbook

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The original plan used IRS publications and 10-Ks. That frames the project as finance-only, and those documents are almost entirely text. We want the project to read as general-purpose, and to show real-world multimodal problems: content that exists only in a chart or diagram, routing different element types to different models, and handling parse failures.

## Options considered
- **IRS publications.** Clean public PDFs, but text-only and finance-specific.
- **EU AI Act, NIST SP 800-53 and CSF 2.0.** Topical and well structured, but almost no images.
- **arXiv ML papers.** Relevant to AI roles and full of results charts. Licences vary per paper (we'd have to choose CC-BY ones), and figure styles are inconsistent.
- **FAA *Pilot's Handbook of Aeronautical Knowledge* (FAA-H-8083-25).** A public-domain US government work of about 500 pages with stable page numbers. It has hundreds of figures, many of them load-bearing (instrument diagrams, labelled drawings, performance charts you must read to answer a question), plus decorative photos.
- **SEC 10-K filings.** Recognisable companies, dense text and financial tables.

## Decision
Two corpora: **SEC 10-Ks** and the **FAA Pilot's Handbook**. The repo is renamed from `fin-doc-rag` to `multimodal-doc-rag`.

## Why
The two differ in format (HTML vs PDF), in structure (tables vs figures), and in domain (finance vs aviation and technical manuals). Running one pipeline and one eval across both shows the system generalises. The handbook's mix of informational and decorative images forces a realistic routing decision (don't pay a vision model to describe a stock photo). Q&A over technical and maintenance manuals is also a common enterprise RAG use case outside finance.

## Consequences
- EDGAR 10-Ks are HTML or iXBRL, not PDF. Page numbers come from page-break markers and footers, so 10-Ks need their own ingestion path and careful handling of citations.
- Image handling needs its own decision (caption then embed, embed the image directly with a multimodal model, or embed page screenshots), ideally compared in the eval.
- Eval sets are needed for both corpora: a larger primary set and a smaller set to check generalisation.
