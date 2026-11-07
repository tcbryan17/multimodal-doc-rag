"""Download the source documents into `data/` and record them in `data/manifest.json`.

Everything takes an `httpx2.Client` so tests can swap in a MockTransport. Nothing here runs at
import time and nothing is committed: `data/` is gitignored (ADR 0013).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx2

from multimodal_doc_rag.types import Corpus, SourceInfo

FAA_PHAK_URL = "https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/phak"
FAA_TITLE_PREFIX = "FAA-H-8083-25C"
# A polite generic agent for the FAA (no email needed there).
FAA_USER_AGENT = "multimodal-doc-rag/0.1"

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
# ADR 0013: dev = Apple, Microsoft, J&J; held out = Costco.
EDGAR_TICKERS = ("AAPL", "MSFT", "JNJ", "COST")
HELDOUT_TICKERS = frozenset({"COST"})
# SEC registrant names are legal names in mixed styles ("COSTCO WHOLESALE CORP /NEW",
# "Apple Inc."). Titles appear in every citation, so ours use a short consistent name.
EDGAR_DISPLAY_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "JNJ": "Johnson & Johnson",
    "COST": "Costco",
}
# SEC allows 10 req/s; we stay at ~5 to leave headroom.
SEC_MIN_INTERVAL_S = 0.2

# Held out from all tuning, scored once at the end (ADR 0011/0013): performance charts,
# weather services and airspace diagrams. Ch. 8 is deliberately NOT held out: the PDF
# parser was developed against it.
FAA_HELDOUT_KEYS = frozenset({"phak-ch11", "phak-ch13", "phak-ch15"})

SPLIT_DEV = "dev"
SPLIT_HELDOUT = "heldout"


class MissingUserAgentError(RuntimeError):
    """Raised before any SEC request when SEC_USER_AGENT is not configured."""


@dataclass(frozen=True)
class ChapterLink:
    doc_key: str  # e.g. "phak-ch08"
    display_title: str  # e.g. "Ch. 8: Flight Instruments"
    url: str  # absolute


@dataclass(frozen=True)
class ManifestEntry:
    doc_key: str
    corpus: Corpus
    title: str
    source_url: str
    company: str | None
    fiscal_year: int | None
    path: str  # relative to the data dir, POSIX style
    sha256: str
    split: str  # "dev" | "heldout"

    def to_source_info(self) -> SourceInfo:
        return SourceInfo(
            doc_key=self.doc_key,
            corpus=self.corpus,
            title=self.title,
            source_url=self.source_url,
            company=self.company,
            fiscal_year=self.fiscal_year,
        )


# --- manifest -----------------------------------------------------------------------------


def manifest_path(data_dir: Path) -> Path:
    return data_dir / "manifest.json"


def _by_key(entry: ManifestEntry) -> str:
    return entry.doc_key


def load_manifest(data_dir: Path) -> list[ManifestEntry]:
    path = manifest_path(data_dir)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ManifestEntry(**{**item, "corpus": Corpus(item["corpus"])}) for item in raw]


def save_manifest(data_dir: Path, entries: list[ManifestEntry]) -> None:
    """Deterministic: sorted by doc_key, sorted keys, trailing newline (clean diffs)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(e) | {"corpus": e.corpus.value} for e in sorted(entries, key=_by_key)]
    text = json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    manifest_path(data_dir).write_text(text, encoding="utf-8")


def merge_manifest(existing: list[ManifestEntry], new: list[ManifestEntry]) -> list[ManifestEntry]:
    """New entries replace old ones with the same doc_key, so `--faa` and `--edgar` can be
    run separately without wiping each other."""
    merged = {e.doc_key: e for e in existing}
    merged.update({e.doc_key: e for e in new})
    return sorted(merged.values(), key=_by_key)


# --- shared download helper -----------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(client: httpx2.Client, url: str, dest: Path, headers: dict[str, str]) -> bool:
    """Download `url` to `dest`. Returns False (and writes nothing) if a file with the same size
    is already there, judged by Content-Length before the body is read."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length is not None and dest.exists() and dest.stat().st_size == int(length):
            return False
        # Write to a temp name then rename, so an interrupted download never leaves a
        # truncated file that a later run would mistake for complete.
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
        tmp.replace(dest)
        return True


# --- FAA ----------------------------------------------------------------------------------

_CHAPTER_TEXT = re.compile(r"^Chapter\s+(\d+)\s*:\s*(.+)$")
# Non-chapter parts of the handbook we ingest, keyed by the last URL segment. The table of
# contents is deliberately absent: it is a list of page numbers and would only add retrieval noise.
_FAA_EXTRA = {
    "front-matter": ("phak-front", "Front Matter"),
    "appendices": ("phak-appendices", "Appendices"),
    "glossary": ("phak-glossary", "Glossary"),
    "index": ("phak-index", "Index"),
}


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href = None


def faa_chapter_links(html: str, base_url: str) -> list[ChapterLink]:
    """Per-part landing-page links from the PHAK index page, in page order.

    On the live page the hrefs are slugs like `/.../phak/chapter-8-flight-instruments`. Each slug
    is an HTML page that links to the actual PDF (see `chapter_pdf_url`), so we match on the link
    text and the last path segment. The "Full Version" single-PDF link is skipped: the parts
    already cover it.
    """
    parser = _AnchorCollector()
    parser.feed(html)
    links: list[ChapterLink] = []
    for href, raw_text in parser.anchors:
        if "/phak/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        text = " ".join(raw_text.replace("\xa0", " ").split())  # nbsp -> space, collapse runs
        url = urljoin(base_url, href)
        if match := _CHAPTER_TEXT.match(text):
            number = int(match.group(1))
            links.append(
                ChapterLink(f"phak-ch{number:02d}", f"Ch. {number}: {match.group(2)}", url)
            )
        elif slug in _FAA_EXTRA:
            key, title = _FAA_EXTRA[slug]
            links.append(ChapterLink(key, title, url))
    return links


def chapter_pdf_url(html: str, page_url: str) -> str:
    """The PDF link on one part's landing page, e.g. `/sites/faa.gov/files/10_phak_ch8.pdf`."""
    parser = _AnchorCollector()
    parser.feed(html)
    for href, _ in parser.anchors:
        if href.split("?", 1)[0].lower().endswith(".pdf"):
            return urljoin(page_url, href)
    raise LookupError(f"no PDF link found on {page_url}")


def fetch_faa(client: httpx2.Client, data_dir: Path) -> list[ManifestEntry]:
    headers = {"User-Agent": FAA_USER_AGENT}
    page = client.get(FAA_PHAK_URL, headers=headers, follow_redirects=True)
    page.raise_for_status()
    entries: list[ManifestEntry] = []
    for link in faa_chapter_links(page.text, FAA_PHAK_URL):
        landing = client.get(link.url, headers=headers, follow_redirects=True)
        landing.raise_for_status()
        pdf_url = chapter_pdf_url(landing.text, link.url)
        dest = data_dir / "faa" / f"{link.doc_key}.pdf"
        download(client, pdf_url, dest, headers)
        # Guard against saving an HTML page (an error page, or a landing page) under a .pdf
        # name: every real PDF starts with these magic bytes.
        with dest.open("rb") as fh:
            if fh.read(5) != b"%PDF-":
                dest.unlink()
                raise ValueError(f"{pdf_url} did not return a PDF")
        entries.append(
            ManifestEntry(
                doc_key=link.doc_key,
                corpus=Corpus.FAA,
                title=f"{FAA_TITLE_PREFIX}, {link.display_title}",
                source_url=pdf_url,
                company=None,
                fiscal_year=None,
                path=dest.relative_to(data_dir).as_posix(),
                sha256=_sha256(dest),
                split=SPLIT_HELDOUT if link.doc_key in FAA_HELDOUT_KEYS else SPLIT_DEV,
            )
        )
    return entries


# --- EDGAR --------------------------------------------------------------------------------


def require_sec_user_agent(user_agent: str | None) -> str:
    if not user_agent or not user_agent.strip():
        raise MissingUserAgentError(
            "SEC EDGAR requires a User-Agent with a real contact. Set SEC_USER_AGENT in .env, "
            'e.g. SEC_USER_AGENT="Your Name you@example.com" (see .env.example).'
        )
    return user_agent.strip()


def pad_cik(cik: int | str) -> str:
    return f"{int(cik):010d}"


def display_name(ticker: str, sec_name: str) -> str:
    """Short name for titles; unknown tickers fall back to the SEC name minus a state suffix
    like " /NEW" or " /DE/"."""
    known = EDGAR_DISPLAY_NAMES.get(ticker.upper())
    return known if known is not None else re.sub(r"\s*/[A-Z]+/?$", "", sec_name)


def lookup_company(tickers_json: dict[str, Any], ticker: str) -> tuple[str, str]:
    """(zero-padded CIK, company name) for a ticker from company_tickers.json."""
    for row in tickers_json.values():
        if row["ticker"].upper() == ticker.upper():
            return pad_cik(row["cik_str"]), str(row["title"])
    raise KeyError(f"ticker {ticker!r} not found in company_tickers.json")


@dataclass(frozen=True)
class Filing:
    accession_number: str
    primary_document: str
    report_date: str
    filing_date: str

    @property
    def fiscal_year(self) -> int:
        # Rule: the calendar year in which the fiscal period ends (reportDate). That gives
        # Apple FY2026 for a Sept 2026 year-end and matches the doc_key `aapl-10k-2026`. It
        # would be off by one for a filer whose year ends in January, and none are in the
        # corpus. Falls back to filingDate's year if reportDate is empty.
        return int((self.report_date or self.filing_date)[:4])


def latest_10k(submissions: dict[str, Any]) -> Filing:
    """Most recent filing whose form is exactly '10-K'. Amendments ('10-K/A') are excluded
    because they are often partial (e.g. Part III only). Newest by filingDate, so we don't
    depend on EDGAR's array ordering."""
    recent = submissions["filings"]["recent"]
    candidates = [
        Filing(acc, doc, report, filed)
        for form, acc, doc, report, filed in zip(
            recent["form"],
            recent["accessionNumber"],
            recent["primaryDocument"],
            recent["reportDate"],
            recent["filingDate"],
            strict=True,
        )
        if form == "10-K"
    ]
    if not candidates:
        raise LookupError("no 10-K found in recent filings")
    return max(candidates, key=lambda f: f.filing_date)


def archive_url(cik: str, filing: Filing) -> str:
    # The archive path uses the CIK without padding and the accession number without dashes.
    return SEC_ARCHIVE_URL.format(
        cik=int(cik),
        accession=filing.accession_number.replace("-", ""),
        document=filing.primary_document,
    )


def fetch_edgar(
    client: httpx2.Client,
    data_dir: Path,
    user_agent: str | None,
    tickers: tuple[str, ...] = EDGAR_TICKERS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[ManifestEntry]:
    headers = {"User-Agent": require_sec_user_agent(user_agent)}  # raises before any request
    last_request = float("-inf")

    def throttle() -> None:
        """Keep at least SEC_MIN_INTERVAL_S between consecutive SEC requests."""
        nonlocal last_request
        wait = SEC_MIN_INTERVAL_S - (clock() - last_request)
        if wait > 0:
            sleep(wait)
        last_request = clock()

    def get_json(url: str) -> Any:
        throttle()
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    tickers_json = get_json(SEC_TICKERS_URL)
    entries: list[ManifestEntry] = []
    for ticker in tickers:
        cik, company = lookup_company(tickers_json, ticker)
        filing = latest_10k(get_json(SEC_SUBMISSIONS_URL.format(cik=cik)))
        url = archive_url(cik, filing)
        doc_key = f"{ticker.lower()}-10k-{filing.fiscal_year}"
        dest = data_dir / "edgar" / f"{doc_key}{Path(filing.primary_document).suffix or '.htm'}"
        throttle()
        download(client, url, dest, headers)
        entries.append(
            ManifestEntry(
                doc_key=doc_key,
                corpus=Corpus.TEN_K,
                title=f"{display_name(ticker, company)} 10-K FY{filing.fiscal_year}",
                source_url=url,
                company=company,
                fiscal_year=filing.fiscal_year,
                path=dest.relative_to(data_dir).as_posix(),
                sha256=_sha256(dest),
                split=SPLIT_HELDOUT if ticker.upper() in HELDOUT_TICKERS else SPLIT_DEV,
            )
        )
    return entries
