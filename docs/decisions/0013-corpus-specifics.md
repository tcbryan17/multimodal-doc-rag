# 0013. Corpus specifics

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
0004 chose the two corpora but not which filings or which handbook edition. The eval (0011) needs dev and held-out sets that test generalisation.

Some filers, many banks among them, put their financial statements in an attached annual-report exhibit rather than in the 10-K itself. That breaks the assumption that the answer is in the document we ingest.

The current handbook edition is **FAA-H-8083-25C** (November 2023). The FAA publishes it as separate PDFs per chapter (17 chapters plus appendices), and its printed page numbers are chapter-style ("4-12").

## Options considered
**10-Ks**
- **Big tech** (Apple, NVIDIA, Tesla; held-out Microsoft). Recognisable, but all the same sector, so the held-out result proves less.
- **Smaller start** (Apple, Microsoft; held-out Costco). Less work, but fewer table styles.
- **Mixed industries.**

**Handbook**
- **A figure-heavy subset** (about 6 chapters). Faster, but a smaller and less realistic corpus.
- **All chapters.**

## Decision
- **10-Ks:** the latest annual filing for each company, one year each (comparison questions are out of scope; see 0005).
  - **Dev set:** Apple, Microsoft, Johnson & Johnson (tech, software, healthcare).
  - **Held-out set:** Costco (retail).

  All four include their financial statements directly in the 10-K.
- **Handbook:** FAA-H-8083-25C, **all chapters and appendices**, downloaded from the FAA's handbook page. About 3 chapters are held out from tuning, including a chart-heavy one (Ch. 11, Aircraft Performance).
- Each source file is one document. A handbook chapter's display title looks like "FAA-H-8083-25C, Ch. 4: Principles of Flight".

## Why
Mixing industries varies the vocabulary and table layouts, so a good held-out score means something. The whole handbook is still cheap to process: describing every figure costs well under $1.

## Consequences
- Fetch scripts download into `data/` (gitignored). The SEC requires a contact in the User-Agent header, so the owner chooses what goes there.
- If a newer filing or handbook edition appears, it's ingested as a new document. Existing gold-set items stay pinned to their version.
