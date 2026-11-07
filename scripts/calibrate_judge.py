"""Measure how often the LLM judge agrees with you (ADR 0011).

  uv run python scripts/calibrate_judge.py sample --report evals/reports/<run>.json --n 30
  uv run python scripts/calibrate_judge.py grade --name <run>
  uv run python scripts/calibrate_judge.py agreement --name <run>

`sample` hides the judge's verdicts from the grading view; do not open the .jsonl in an
editor while you grade. `agreement` writes evals/calibration/<name>.md for the eval report.
"""

import argparse
from pathlib import Path

from multimodal_doc_rag.evals.calibration import (
    CalibrationError,
    agreement,
    grade_loop,
    load_entries,
    render_summary,
    sample_entries,
    save_entries,
)
from multimodal_doc_rag.evals.results import EvalReport

ROOT = Path(__file__).resolve().parent.parent
CAL = ROOT / "evals" / "calibration"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--report", required=True, type=Path, help="a reports/*.json from run_eval")
    s.add_argument("--n", type=int, default=30)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--name", help="default: the report's file name")
    for name in ("grade", "agreement"):
        sub.add_parser(name).add_argument("--name", required=True)
    a = p.parse_args()

    try:
        if a.cmd == "sample":
            report = EvalReport.model_validate_json(a.report.read_text(encoding="utf-8"))
            name = a.name or a.report.stem
            entries = sample_entries(report, a.n, a.seed)
            save_entries(CAL / f"{name}.jsonl", entries)
            print(f"wrote {len(entries)} items to evals/calibration/{name}.jsonl")
            print(f"next: uv run python scripts/calibrate_judge.py grade --name {name}")
            return 0
        path = CAL / f"{a.name}.jsonl"
        entries = load_entries(path)
        if a.cmd == "grade":
            n = grade_loop(entries, input, print, lambda cur: save_entries(path, cur))
            print(f"graded {n} this session")
            return 0
        report_md = render_summary(agreement(entries))
        (CAL / f"{a.name}.md").write_text(report_md, encoding="utf-8")
        print(report_md)
        return 0
    except CalibrationError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
