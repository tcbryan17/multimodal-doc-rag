# 1. Parsing and figure regions

## What it does
Parsing turns a source file into a list of elements in reading order. Each element keeps its page (a 0-based index and the printed label), its section path and its kind (text, table or figure). The FAA handbook is a PDF, read with PyMuPDF and our own layout rules. A heading is found by font and size: 16 pt or more is a chapter, bold Helvetica near 12 pt is a section, bold Helvetica near 10 pt (60 characters or fewer) is a subsection. Figures are the hard part. 57 of the 73 figures in the two spike chapters are vector drawings, so there is no image to extract. The parser finds each caption ("Figure N-M."), picks the drawings that belong to it, takes the union, and renders that region at 130 DPI. The 10-Ks are HTML, parsed by hand with BeautifulSoup. Pages are rebuilt from CSS page-break markers, and the printed label comes from the footer line (1 to 3 digits, "F-7" or a roman numeral).

## Where it lives
- `src/multimodal_doc_rag/parsing/handbook_pdf.py::heading_level`
- `src/multimodal_doc_rag/parsing/handbook_pdf.py::reading_order`
- `src/multimodal_doc_rag/parsing/handbook_pdf.py::find_captions`
- `src/multimodal_doc_rag/parsing/handbook_pdf.py::assign_owners`
- `src/multimodal_doc_rag/parsing/handbook_pdf.py::figure_region`
- `src/multimodal_doc_rag/parsing/handbook_pdf.py::HandbookPdfParser`
- `src/multimodal_doc_rag/parsing/edgar.py::EdgarHtmlParser`
- `src/multimodal_doc_rag/parsing/edgar.py::_split_pages`
- `src/multimodal_doc_rag/parsing/edgar.py::_footer_label`
- `src/multimodal_doc_rag/types.py::Element`
- `src/multimodal_doc_rag/types.py::Figure`

## What was chosen and why
ADR 0006. EDGAR HTML is parsed by hand with BeautifulSoup and lxml, because the structure is already in the markup and a library would add little we could not explain. For the PDF, a spike ran PyMuPDF and Docling on Chapters 8 and 11 (73 figures) before the choice. PyMuPDF found 73 of 73 figures and linked 73 of 73 figure numbers. Docling found 71 (3 of them false), misread 2 figure numbers, and rendered instrument dial faces blank (Figs. 8-22, 8-24, 8-32), which destroys the information a question needs. PyMuPDF also ran in 2 to 6 seconds per chapter against 14 to 75 seconds for Docling, and needs no PyTorch. The price is that we own the layout rules. Both parsers sit behind one `Parser` protocol, so the chunker does not care which one produced the elements.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| Docling (IBM) for the PDF | Blank instrument dials in crops, every heading flattened to level 1, 109 packages including PyTorch, 14 to 75 s per chapter | If other chapters made our layout rules unmanageable, or the source were scanned pages with no text layer |
| Docling headings plus PyMuPDF crops (hybrid) | Two dependencies and two structures to reconcile | If heading accuracy became the bottleneck and the crops were already fine |
| Deciding on paper, no spike | We did not know the raster/vector mix, and it turned out to be mostly vector | Never for a fact this cheap to measure |
| `edgartools` for 10-Ks | Hides the logic, and page-number handling still needs our own code | If we needed many filing types and did not care about page-level citations |
| Extracting embedded images only | Misses the 57 of 73 vector figures | A corpus that is all raster photos |

## Evidence
- Spike table in ADR 0006: 73/73 figures and 73/73 figure numbers (PyMuPDF) against 71 with 3 false positives (Docling). About 3 of 73 PyMuPDF crops were visibly wrong (for example 8-38 merged with 8-37). About 21 headings were missed before the "Sample Problem" rule was added.
- Real ingest, `reports/ingest/20261109T162956Z-ingest.md`: 25 documents ingested, 496 FAA figures found.
- Not measured yet: heading accuracy across all 17 chapters (the spike judged 2 chapters by eye). To measure it, hand-label the headings of three more chapters and score `heading_level` against them. Page-label accuracy on the full corpus is also unmeasured.

## Interview questions
1. Most figures in the handbook are vector drawings. Why can you not just extract the images, and how does `figure_region` decide where a figure starts and ends?

**Your answer:**

2. Why did you hand-roll the EDGAR parser instead of using `edgartools`, and what does a printed page label cost you that a file page index would not?

**Your answer:**

3. The spike tested 2 of 17 chapters. What could go wrong on the other 15, and how would you find out cheaply?

**Your answer:**

4. PyMuPDF is AGPL. What does that mean for this project today, and for a closed-source deployment?

**Your answer:**

5. How do `assign_owners` and the ceiling rule keep two adjacent figures apart? Give the Fig 8-37 and 8-38 example.

**Your answer:**
