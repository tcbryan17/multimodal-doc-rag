"""Turn replay/sample-run.json into the portfolio site's replay events (no model calls).

  uv run python scripts/export_site_replay.py --site-dir ../portfolio-site

The site is static, and its player shows `{t, who, text, image?}` events. This writes each
cited figure as a PNG under <site-dir>/assets/replays/ (instead of pasting ~70 KB of base64
per figure into projects.js) and prints the events as JSON to paste into that project's
`replay.events`. The question comes from replay/sample-run.meta.json (saved by
save_replay.py), because the /ask response itself has no room for it.
"""

import argparse
import json
import sys
from pathlib import Path

from multimodal_doc_rag.contracts import AskResponse
from multimodal_doc_rag.replay import decode_data_uri, site_events

REPLAY = Path("replay/sample-run.json")
META = Path("replay/sample-run.meta.json")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--site-dir", type=Path, required=True, help="the portfolio-site checkout")
    p.add_argument("--prefix", default="rag", help="file name prefix for the figure PNGs")
    args = p.parse_args()

    if not (args.site_dir / "projects.js").exists():
        print(f"{args.site_dir} has no projects.js; is it the site checkout?", file=sys.stderr)
        return 2
    response = AskResponse.model_validate_json(REPLAY.read_text())
    question = json.loads(META.read_text())["question"]

    out_dir = args.site_dir / "assets" / "replays"
    out_dir.mkdir(parents=True, exist_ok=True)
    srcs: list[str | None] = []
    for n, citation in enumerate(response.citations, start=1):
        if citation.image_url and citation.image_url.startswith("data:"):
            name = f"{args.prefix}-{n}.png"
            (out_dir / name).write_bytes(decode_data_uri(citation.image_url))
            srcs.append(f"assets/replays/{name}")  # relative to the site root
        else:
            srcs.append(None)
    print(json.dumps(site_events(question, response, srcs), indent=2, ensure_ascii=False))
    written = sum(s is not None for s in srcs)
    print(f"wrote {written} figure(s) to {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
