"""Is the system ready to release? Checks every pre-registered gate (ADR 0016, evals/gates.toml).

  uv run python scripts/release_check.py \\
      --final evals/reports/<stamp>-final.json \\
      --injection evals/reports/<stamp>-direct-injection.json \\
      --injection evals/reports/<stamp>-indirect-injection.json \\
      --calibration <name>

Makes no model calls. It reads the committed reports, the calibration grades
(evals/calibration/<name>.jsonl) and figure coverage from the database. Writes
evals/reports/<stamp>-release-check.md.

Exit code 0 means ready. 1 means blocked: a gate failed, or its evidence is missing or not
eligible. 2 means a usage error. Deployment runs this and refuses to ship on a non-zero exit.
"""

import argparse
import sys
from pathlib import Path

import psycopg

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.evals.calibration import CalibrationError, agreement, load_entries
from multimodal_doc_rag.evals.gates import (
    figure_coverage_counts,
    load_gates,
    load_minimums,
    release_check,
    render_release_check,
)
from multimodal_doc_rag.evals.index import db_name
from multimodal_doc_rag.evals.report import report_basename
from multimodal_doc_rag.evals.results import EvalReport
from multimodal_doc_rag.evals.runner import utc_stamp

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"


def _load(path: Path) -> EvalReport:
    return EvalReport.model_validate_json(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--final", type=Path, help="the held-out final run report (.json)")
    p.add_argument("--injection", type=Path, action="append", default=[], help="repeatable")
    p.add_argument("--calibration", help="name of evals/calibration/<name>.jsonl")
    p.add_argument("--database-url", help="default: DATABASE_URL (the real index, not rag_eval)")
    p.add_argument("--gates", type=Path, default=EVALS / "gates.toml")
    a = p.parse_args()

    for path in [a.final, *a.injection]:
        if path is not None and not path.exists():
            print(f"error: no such report: {path}", file=sys.stderr)
            return 2
    gates, minimums = load_gates(a.gates), load_minimums(a.gates)
    final = _load(a.final) if a.final else None
    injections = [_load(path) for path in a.injection]
    evidence = [f"held-out final: {_rel(a.final) if a.final else 'none'}"]
    evidence += [f"injection: {_rel(path)}" for path in a.injection] or ["injection: none"]

    cal = None
    if a.calibration:
        cal_path = EVALS / "calibration" / f"{a.calibration}.jsonl"
        try:
            cal = agreement(load_entries(cal_path))
        except (CalibrationError, FileNotFoundError) as exc:
            print(f"warning: calibration not usable ({exc}); judge_kappa is not measured")
        evidence.append(f"calibration: {_rel(cal_path)}")
    else:
        evidence.append("calibration: none")

    url = a.database_url or settings.database_url.get_secret_value()
    with psycopg.connect(url) as conn:
        figures = figure_coverage_counts(conn)
    evidence.append(f"figure coverage: database {db_name(url)!r}")

    check = release_check(final, injections, cal, figures, gates, minimums)
    started = utc_stamp()
    md = render_release_check(check, gates, evidence, started)
    out = EVALS / "reports" / f"{report_basename(started, 'release-check')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"wrote {_rel(out)}")
    return 0 if check.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
