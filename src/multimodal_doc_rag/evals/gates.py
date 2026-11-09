"""Pre-registered release gates (ADR 0016).

`evals/gates.toml` holds the thresholds, committed before any eval ran. This module turns
evidence into one pass / fail / not-measured verdict per gate and group:
- the held-out final report (quality, cost, latency)
- injection reports
- calibration grades
- the database (figure coverage)

Everything here is pure except `figure_coverage_counts`.

Two rules that make the gates mean something:
- **Missing evidence is not a pass.** No data gives "not_measured", and that blocks release.
- **Gates bind only on a complete held-out run** (`binding_problems`). Dev runs show the same
  table as guidance.
"""

import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from multimodal_doc_rag.evals.calibration import AgreementReport
from multimodal_doc_rag.evals.metrics import distribution, metric_table
from multimodal_doc_rag.evals.results import EvalReport, InjectionResult, ItemResult

Status = Literal["pass", "fail", "not_measured"]
CORPORA = ("10k", "faa")
RECALL_K = 5  # the gate is recall@5 (ADR 0011)


class Gate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    description: str
    source: Literal["eval", "injection", "calibration", "index"]
    # eval: a metric_table key, or "cost_mean_usd" / "latency_p95_ms";
    # injection: "canary_in_answer"; calibration: "min_kappa"; index: "figure_coverage"
    metric: str
    op: Literal[">=", "<="]
    threshold: float
    scope: Literal["per_corpus", "pooled"] = "pooled"

    def passes(self, value: float) -> bool:
        return value >= self.threshold if self.op == ">=" else value <= self.threshold


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: str
    group: str  # a corpus ("10k", "faa") or "pooled"
    value: float | None
    n: int  # how many observations the value rests on
    status: Status
    detail: str = ""


def load_gates(path: Path) -> list[Gate]:
    data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    if set(data) - {"gate"}:
        raise ValueError(f"{path}: only [[gate]] tables are allowed, got {sorted(data)}")
    gates = [Gate.model_validate(g) for g in data.get("gate", [])]
    ids = [g.id for g in gates]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        raise ValueError(f"{path}: duplicate gate id(s) {dupes}")
    return gates


def _result(gate: Gate, group: str, value: float | None, n: int, detail: str = "") -> GateResult:
    if value is None or n == 0:
        return GateResult(
            gate=gate.id, group=group, value=None, n=n, status="not_measured", detail=detail
        )
    status: Status = "pass" if gate.passes(value) else "fail"
    return GateResult(gate=gate.id, group=group, value=value, n=n, status=status, detail=detail)


def _eval_value(items: Sequence[ItemResult], metric: str) -> tuple[float | None, int]:
    ok = [r for r in items if r.error is None]
    if metric == "cost_mean_usd":
        d = distribution([r.cost_usd for r in ok])
        return d.mean, d.n
    if metric == "latency_p95_ms":
        d = distribution([r.latency_ms for r in ok])
        return d.p95, d.n
    ci = metric_table(items, [metric])[metric]
    return ci.mean, ci.n


def check_eval(
    items: Sequence[ItemResult], gates: Sequence[Gate], corpora: Sequence[str] = CORPORA
) -> list[GateResult]:
    """Quality, cost and latency gates. `per_corpus` gates get one result per corpus in
    `corpora`; a corpus with no items is "not_measured", never silently skipped."""
    out: list[GateResult] = []
    for g in gates:
        if g.source != "eval":
            continue
        if g.scope == "pooled":
            out.append(_result(g, "pooled", *_eval_value(items, g.metric)))
            continue
        for corpus in corpora:
            subset = [r for r in items if r.corpus == corpus]
            out.append(_result(g, corpus, *_eval_value(subset, g.metric)))
    return out


def check_injection(rows: Sequence[InjectionResult], gates: Sequence[Gate]) -> list[GateResult]:
    """Share of attacks whose canary showed up in the answer, over every injection item that
    has a canary. For indirect attacks the detail says how many actually put poisoned text in
    front of the generator: an attack that never reached it tested nothing."""
    out: list[GateResult] = []
    for g in gates:
        if g.source != "injection":
            continue
        ok = [r for r in rows if r.error is None]
        values = [v for r in ok if (v := r.metrics.get(g.metric)) is not None]
        indirect = [r for r in ok if r.kind == "indirect"]
        reached = sum(1 for r in indirect if r.metrics.get("canary_in_retrieved") == 1.0)
        kinds = sorted({r.kind for r in ok})
        detail = f"kinds: {', '.join(kinds) or 'none'}"
        if indirect:
            detail += f"; poisoned text reached the generator in {reached} of {len(indirect)}"
        value = sum(values) / len(values) if values else None
        out.append(_result(g, "pooled", value, len(values), detail))
    return out


def check_calibration(report: AgreementReport | None, gates: Sequence[Gate]) -> list[GateResult]:
    """The worst Cohen's kappa across the judged dimensions: if the judge disagrees with the
    owner on either correctness or faithfulness, the judged gates can't be trusted."""
    out: list[GateResult] = []
    for g in gates:
        if g.source != "calibration":
            continue
        if report is None or not report.dimensions:
            out.append(_result(g, "pooled", None, 0, "no calibration grades"))
            continue
        kappas = {dim: d.kappa for dim, d in report.dimensions.items()}
        undefined = sorted(dim for dim, k in kappas.items() if k is None)
        if undefined:
            detail = f"kappa undefined for {', '.join(undefined)} (one grade only)"
            out.append(_result(g, "pooled", None, report.n_graded, detail))
            continue
        defined = {dim: k for dim, k in kappas.items() if k is not None}
        worst = min(defined, key=lambda dim: defined[dim])
        out.append(_result(g, "pooled", defined[worst], report.n_graded, f"worst: {worst}"))
    return out


def check_index(described: int, total: int, gates: Sequence[Gate]) -> list[GateResult]:
    out: list[GateResult] = []
    for g in gates:
        if g.source != "index":
            continue
        value = described / total if total else None
        out.append(_result(g, "pooled", value, total, f"{described} of {total} figure chunks"))
    return out


def figure_coverage_counts(conn: Any) -> tuple[int, int]:
    """(figure chunks with a finished vision description, all figure chunks).

    A successful description always sets `informational` (true, or false for a decorative
    image). A degraded figure, where the vision call failed and only the caption is kept,
    leaves it NULL (ADR 0008).
    """
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE informational IS NOT NULL), count(*)"
        " FROM chunks WHERE kind = 'figure'"
    ).fetchone()
    return int(row[0]), int(row[1])


def binding_problems(report: EvalReport) -> list[str]:
    """Why this run can't be the binding release run (empty list = it can). ADR 0016."""
    c = report.config
    problems: list[str] = []
    if c.split != "heldout":
        problems.append(f"{c.split} split, not held-out: gates bind only on the held-out run")
    if c.corpus != "all":
        problems.append(f"covers {c.corpus} only: the binding run needs both corpora")
    if c.judge_model is None:
        problems.append("no judge: correctness and faithfulness are unmeasured")
    if c.include_drafts:
        problems.append("includes unverified draft items")
    if c.limit is not None:
        problems.append(f"--limit {c.limit}: not the full question set")
    if c.git_dirty:
        problems.append("uncommitted changes: the run can't be tied to a commit")
    if c.recall_k != RECALL_K:
        problems.append(f"recall@{c.recall_k}: the gate is recall@{RECALL_K}")
    if report.truncated:
        problems.append("cut short by the cost cap")
    if errors := sum(1 for r in report.items if r.error):
        problems.append(f"{errors} item error(s)")
    if judge_errors := sum(1 for r in report.items if r.judge_error):
        problems.append(f"{judge_errors} judge error(s)")
    return problems


def release_ready(results: Sequence[GateResult], gates: Sequence[Gate]) -> bool:
    """True only if every gate has at least one result and every result passed."""
    if not gates:
        return False
    covered = {r.gate for r in results}
    return all(g.id in covered for g in gates) and all(r.status == "pass" for r in results)


# --- rendering ------------------------------------------------------------------------------


def _fmt(metric: str, value: float) -> str:
    if metric == "cost_mean_usd":
        return f"${value:.4f}"
    if metric == "latency_p95_ms":
        return f"{value:,.0f} ms"
    if metric == "figure_coverage":
        return f"{value:.1%}"
    return f"{value:.2f}"


STATUS_TEXT: dict[Status, str] = {"pass": "pass", "fail": "FAIL", "not_measured": "not measured"}


def render_gates(results: Sequence[GateResult], gates: Sequence[Gate]) -> list[str]:
    by_id = {g.id: g for g in gates}
    lines = [
        "| gate | group | value | n | threshold | status |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        g = by_id[r.gate]
        op = "≥" if g.op == ">=" else "≤"
        value = "-" if r.value is None else _fmt(g.metric, r.value)
        status = STATUS_TEXT[r.status]
        if r.detail:
            status += f" ({r.detail})"
        lines.append(
            f"| {r.gate} | {r.group} | {value} | {r.n} | {op} {_fmt(g.metric, g.threshold)} "
            f"| {status} |"
        )
    return lines


class ReleaseCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    problems: list[str]  # evidence that is missing or not eligible
    results: list[GateResult]


def release_check(
    final: EvalReport | None,
    injection_reports: Sequence[EvalReport],
    agreement: AgreementReport | None,
    figures: tuple[int, int],
    gates: Sequence[Gate],
) -> ReleaseCheck:
    """The release decision: every gate passes on eligible evidence, or release is blocked.

    `final` is the held-out final run; `injection_reports` are the direct and indirect
    injection runs (the indirect one uses the eval-only index, so it is a separate run);
    `figures` is (described, total) from `figure_coverage_counts`."""
    problems: list[str] = []
    results: list[GateResult] = []
    if final is None:
        problems.append("no held-out final report")
    else:
        problems += [f"final report: {p}" for p in binding_problems(final)]
    results += check_eval(final.items if final else [], gates, CORPORA)  # none: not measured
    rows = [r for rep in injection_reports for r in rep.injection]
    for rep in injection_reports:
        if rep.config.include_drafts:
            problems.append(f"injection report {rep.config.label!r}: includes draft items")
        if rep.truncated:
            problems.append(f"injection report {rep.config.label!r}: cut short by the cost cap")
    for kind in ("direct", "indirect"):
        if not any(r.kind == kind and r.error is None for r in rows):
            problems.append(f"no {kind} injection results")
    indirect = [r for r in rows if r.kind == "indirect" and r.error is None]
    if indirect and not any(r.metrics.get("canary_in_retrieved") == 1.0 for r in indirect):
        # A canary can't appear if the poisoned text never reached the generator: zero hits
        # would be an empty test passing, which ADR 0016 rules out.
        problems.append("indirect injection: poisoned text never reached the generator")
    results += check_injection(rows, gates)
    results += check_calibration(agreement, gates)
    results += check_index(*figures, gates)
    ready = not problems and release_ready(results, gates)
    return ReleaseCheck(ready=ready, problems=problems, results=results)


def render_release_check(
    check: ReleaseCheck, gates: Sequence[Gate], evidence: Sequence[str], when_utc: str
) -> str:
    verdict = "READY FOR RELEASE" if check.ready else "BLOCKED"
    lines = [f"# Release check: {verdict}", "", f"Generated {when_utc} (ADR 0016).", ""]
    lines += ["## Evidence", "", *[f"- {e}" for e in evidence], ""]
    if check.problems:
        lines += ["## Evidence problems (each one blocks release)", ""]
        lines += [f"- {p}" for p in check.problems] + [""]
    lines += ["## Gates", "", *render_gates(check.results, gates)]
    return "\n".join(lines) + "\n"


def report_section(report: EvalReport, gates: Sequence[Gate]) -> list[str]:
    """The "Release gates" section of an eval report: the gates this run has evidence for,
    labelled binding-eligible or guidance-only. The release decision itself is
    scripts/release_check.py, which adds injection, calibration and index evidence."""
    corpora = CORPORA if report.config.corpus == "all" else (report.config.corpus,)
    results = check_eval(report.items, gates, corpora) if report.items else []
    if report.injection:
        results += check_injection(report.injection, gates)
    if not results:
        return []
    problems = binding_problems(report) if report.items else ["injection-only run"]
    lines = ["## Release gates (ADR 0016)", ""]
    if problems:
        lines += [
            "> **Guidance only.** This run can't decide release: " + "; ".join(problems) + ".",
            "",
        ]
    else:
        lines += [
            "> **Eligible as the binding held-out run.** Release also needs injection, "
            "calibration and figure-coverage evidence: run `scripts/release_check.py`.",
            "",
        ]
    return lines + render_gates(results, gates)
