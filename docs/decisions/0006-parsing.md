# 0006. Parsing: hand-rolled HTML for EDGAR; the PDF parser is chosen by a spike

- **Status:** Accepted (the PDF parser choice is pending the spike below)
- **Date:** 2026-11-07

## Context
Citations depend on parsing. Every element we extract must keep its page (index and printed label), its section path and its kind (text, table or figure). The two corpora arrive in different formats:
- **EDGAR 10-Ks** are HTML, so the structure already exists. Pages come from CSS `page-break-before/after` markers and footer page numbers. Sections are "Item 1A", "Item 7" and so on. Tables are real `<table>` elements.
- **The FAA handbook** is a PDF, which stores positioned text and drawings, not paragraphs and headings. Figures may be **raster** (embedded images, easy to extract) or **vector** (drawn from lines and text, so there is no image object and the region has to be inferred). We don't yet know the mix.

## Options considered
**EDGAR HTML**
- **Hand-rolled BeautifulSoup + lxml.** A few hundred lines covering page breaks, Item detection and table-to-Markdown. Fully visible.
- **`edgartools`.** Splits filings into Items and handles EDGAR quirks. Faster to start, but page-number handling may still need our own code, and the logic is hidden.

**FAA PDF**
- **PyMuPDF.** Fast. It exposes text blocks, fonts and images with coordinates, and can render any region to PNG. It's explicit and explainable, but vector figures need our own region detection. AGPL licence (fine for a public repo).
- **Docling (IBM, MIT licence).** A layout model detects headings, tables and figures (raster or vector) with captions. Better structure without extra work, but it's a heavy dependency (PyTorch), slower, and more of a black box. It would run only at ingestion time.
- **Decide on paper.** Quicker, but we'd be guessing about the raster/vector mix.

## Decision
- **EDGAR:** hand-rolled BeautifulSoup + lxml.
- **FAA:** run a 1–2 hour **spike** before the parsing and chunking types are designed. Run PyMuPDF and Docling on two figure-heavy chapters and measure:
  - raster vs vector figure count
  - heading accuracy
  - figure–caption pairing
  - speed

  Choose from the evidence, and record the results below.

Both parsers implement one `Parser` protocol, so the chunker and the contract tests don't care which format a document came from.

## Why
The 10-K structure is already in the HTML, so a library adds little we can't explain. For the PDF, the right answer depends on a fact we can measure cheaply, so we measure it rather than guess.

## Spike results
*To be filled in after the spike.*

## Consequences
- The figure element's shape (bounding box, crop, caption link) is designed after the spike.
- If Docling wins, the ingestion environment needs PyTorch. That's acceptable because ingestion runs offline, not in the `/ask` container.
