"""Download the corpus into data/ and update data/manifest.json.

uv run python scripts/fetch_corpus.py [--faa] [--edgar]    (no flags = both)
"""

import argparse

import httpx2

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.fetch import (
    ManifestEntry,
    fetch_edgar,
    fetch_faa,
    load_manifest,
    merge_manifest,
    save_manifest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faa", action="store_true", help="fetch the FAA handbook PDFs")
    parser.add_argument("--edgar", action="store_true", help="fetch the SEC 10-K filings")
    args = parser.parse_args()
    do_faa = args.faa or not args.edgar
    do_edgar = args.edgar or not args.faa

    data_dir = settings.data_dir
    entries: list[ManifestEntry] = []
    # Large PDFs can be slow, so the timeout is generous.
    with httpx2.Client(timeout=120.0) as client:
        if do_edgar:  # first, so a missing SEC_USER_AGENT fails before the big FAA downloads
            entries += fetch_edgar(client, data_dir, settings.sec_user_agent)
        if do_faa:
            entries += fetch_faa(client, data_dir)
    save_manifest(data_dir, merge_manifest(load_manifest(data_dir), entries))
    print(f"Fetched {len(entries)} documents; manifest at {data_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
