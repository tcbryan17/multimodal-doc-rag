"""Fetch tests. No network: every request goes through httpx2.MockTransport."""

import json
from pathlib import Path

import httpx2
import pytest

from multimodal_doc_rag.fetch import (
    FAA_HELDOUT_KEYS,
    FAA_PHAK_URL,
    Filing,
    MissingUserAgentError,
    archive_url,
    faa_chapter_links,
    fetch_edgar,
    fetch_faa,
    latest_10k,
    load_manifest,
    lookup_company,
    merge_manifest,
    pad_cik,
    save_manifest,
)
from multimodal_doc_rag.types import Corpus

FIXTURES = Path(__file__).parent / "fixtures" / "fetch"
PHAK_HTML = (FIXTURES / "phak_page.html").read_text(encoding="utf-8")
TICKERS = json.loads((FIXTURES / "company_tickers.json").read_text(encoding="utf-8"))
SUBMISSIONS = json.loads((FIXTURES / "submissions.json").read_text(encoding="utf-8"))
UA = "Test Person test@example.com"


def make_client(requests: list[httpx2.Request], pdf_bytes: bytes = b"%PDF-fake") -> httpx2.Client:
    """Fake FAA + SEC servers; records every request it sees."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        url = str(request.url)
        if url == FAA_PHAK_URL:
            return httpx2.Response(200, text=PHAK_HTML)
        if url.endswith("company_tickers.json"):
            return httpx2.Response(200, json=TICKERS)
        if url.startswith("https://data.sec.gov/submissions/"):
            return httpx2.Response(200, json=SUBMISSIONS)
        return httpx2.Response(200, content=pdf_bytes)

    return httpx2.Client(transport=httpx2.MockTransport(handler))


# --- FAA ------------------------------------------------------------------------------------


def test_faa_links_titles_and_keys() -> None:
    links = faa_chapter_links(PHAK_HTML, FAA_PHAK_URL)
    assert [(link.doc_key, link.display_title) for link in links] == [
        ("phak-front", "Front Matter"),
        ("phak-ch04", "Ch. 4: Principles of Flight"),
        ("phak-ch07", "Ch. 7: Aircraft Systems"),  # plain space, not nbsp, after the colon
        ("phak-ch08", "Ch. 8: Flight Instruments"),
        ("phak-ch11", "Ch. 11: Aircraft Performance"),
        ("phak-appendices", "Appendices"),
        ("phak-glossary", "Glossary"),
        ("phak-index", "Index"),
    ]  # no table of contents, no full-version PDF, no unrelated links
    assert links[3].url == (
        "https://www.faa.gov/regulationspolicies/handbooksmanuals/aviation/phak/"
        "chapter-8-flight-instruments"
    )


def test_fetch_faa_downloads_and_assigns_split(tmp_path: Path) -> None:
    requests: list[httpx2.Request] = []
    entries = fetch_faa(make_client(requests), tmp_path)
    by_key = {e.doc_key: e for e in entries}
    ch8 = by_key["phak-ch08"]
    assert ch8.title == "FAA-H-8083-25C, Ch. 8: Flight Instruments"
    assert ch8.corpus is Corpus.FAA
    assert ch8.path == "faa/phak-ch08.pdf"
    assert (tmp_path / ch8.path).read_bytes() == b"%PDF-fake"
    assert len(ch8.sha256) == 64
    assert by_key["phak-ch11"].split == "heldout"
    # Exactly the held-out chapters present in the fixture page, nothing else (ADR 0013).
    heldout = {k for k, e in by_key.items() if e.split == "heldout"}
    assert heldout == FAA_HELDOUT_KEYS & by_key.keys()
    assert "phak-ch08" not in FAA_HELDOUT_KEYS  # the parser was developed on Ch. 8
    assert all(r.headers["user-agent"] == "multimodal-doc-rag/0.1" for r in requests)


def test_skips_download_when_same_size_file_exists(tmp_path: Path) -> None:
    (tmp_path / "faa").mkdir()
    existing = tmp_path / "faa" / "phak-ch08.pdf"
    existing.write_bytes(b"OLD-BYTES")  # same length as the b"%PDF-fake" the server sends
    fetch_faa(make_client([]), tmp_path)
    assert existing.read_bytes() == b"OLD-BYTES"  # untouched
    other = tmp_path / "faa" / "phak-ch04.pdf"
    assert other.read_bytes() == b"%PDF-fake"  # a missing file is still downloaded


def test_redownloads_when_size_differs(tmp_path: Path) -> None:
    (tmp_path / "faa").mkdir()
    existing = tmp_path / "faa" / "phak-ch08.pdf"
    existing.write_bytes(b"short")
    fetch_faa(make_client([]), tmp_path)
    assert existing.read_bytes() == b"%PDF-fake"


# --- EDGAR ----------------------------------------------------------------------------------


def test_pad_cik_and_lookup() -> None:
    assert pad_cik(320193) == "0000320193"
    assert pad_cik("789019") == "0000789019"
    assert lookup_company(TICKERS, "aapl") == ("0000320193", "Apple Inc.")
    with pytest.raises(KeyError):
        lookup_company(TICKERS, "NOPE")


def test_latest_10k_ignores_amendments_and_older_filings() -> None:
    filing = latest_10k(SUBMISSIONS)
    assert filing.accession_number == "0000320193-26-000106"  # not the 10-K/A, not the 10-Q
    assert filing.primary_document == "aapl-20260926.htm"
    assert filing.fiscal_year == 2026


def test_latest_10k_raises_when_none() -> None:
    recent = {
        "form": ["10-Q"],
        "accessionNumber": ["a"],
        "primaryDocument": ["d"],
        "reportDate": ["2026-01-01"],
        "filingDate": ["2026-01-02"],
    }
    with pytest.raises(LookupError):
        latest_10k({"filings": {"recent": recent}})


def test_archive_url() -> None:
    filing = Filing("0000320193-26-000106", "aapl-20260926.htm", "2026-09-26", "2026-10-31")
    assert archive_url("0000320193", filing) == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000106/aapl-20260926.htm"
    )


def test_missing_user_agent_raises_before_any_request(tmp_path: Path) -> None:
    requests: list[httpx2.Request] = []
    for bad in (None, "", "   "):
        with pytest.raises(MissingUserAgentError, match="SEC_USER_AGENT"):
            fetch_edgar(make_client(requests), tmp_path, bad)
    assert requests == []


def test_fetch_edgar_sends_configured_user_agent_and_builds_entries(tmp_path: Path) -> None:
    requests: list[httpx2.Request] = []
    sleeps: list[float] = []
    entries = fetch_edgar(
        make_client(requests, b"<html>10-K</html>"),
        tmp_path,
        UA,
        tickers=("AAPL", "COST"),
        sleep=sleeps.append,
        clock=lambda: 0.0,  # frozen clock: every request after the first must wait
    )
    assert requests and all(r.headers["user-agent"] == UA for r in requests)
    aapl, cost = entries
    assert aapl.doc_key == "aapl-10k-2026"
    assert aapl.title == "Apple Inc. 10-K FY2026"
    assert (aapl.company, aapl.fiscal_year, aapl.corpus) == ("Apple Inc.", 2026, Corpus.TEN_K)
    assert aapl.source_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000106/aapl-20260926.htm"
    )
    assert (tmp_path / "edgar" / "aapl-10k-2026.htm").read_bytes() == b"<html>10-K</html>"
    assert (aapl.split, cost.split) == ("dev", "heldout")


def test_rate_limit_sleeps_between_sec_requests(tmp_path: Path) -> None:
    sleeps: list[float] = []
    requests: list[httpx2.Request] = []
    fetch_edgar(
        make_client(requests),
        tmp_path,
        UA,
        tickers=("AAPL",),
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )
    # tickers, submissions, document = 3 requests; the first needs no wait.
    assert len(requests) == 3
    assert sleeps == [0.2, 0.2]


# --- manifest -------------------------------------------------------------------------------


def test_manifest_round_trip_sorted_and_merge(tmp_path: Path) -> None:
    faa = fetch_faa(make_client([]), tmp_path)
    edgar = fetch_edgar(make_client([]), tmp_path, UA, tickers=("AAPL",), sleep=lambda _: None)
    save_manifest(tmp_path, faa + edgar)
    loaded = load_manifest(tmp_path)
    assert loaded == sorted(faa + edgar, key=lambda e: e.doc_key)
    raw = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [r["doc_key"] for r in raw] == sorted(r["doc_key"] for r in raw)
    assert set(raw[0]) == {
        "doc_key", "corpus", "title", "source_url", "company",
        "fiscal_year", "path", "sha256", "split",
    }  # fmt: skip
    # Deterministic: saving again gives byte-identical output.
    before = (tmp_path / "manifest.json").read_bytes()
    save_manifest(tmp_path, loaded)
    assert (tmp_path / "manifest.json").read_bytes() == before
    # Merging replaces by doc_key and keeps the rest.
    assert merge_manifest(loaded, edgar) == loaded


def test_load_manifest_missing_is_empty(tmp_path: Path) -> None:
    assert load_manifest(tmp_path) == []


def test_to_source_info(tmp_path: Path) -> None:
    entry = fetch_edgar(make_client([]), tmp_path, UA, tickers=("AAPL",), sleep=lambda _: None)[0]
    info = entry.to_source_info()
    assert (info.doc_key, info.corpus, info.company, info.fiscal_year) == (
        "aapl-10k-2026",
        Corpus.TEN_K,
        "Apple Inc.",
        2026,
    )
    assert info.source_url == entry.source_url
