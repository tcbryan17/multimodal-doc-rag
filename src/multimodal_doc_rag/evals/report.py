"""Turning an `EvalReport` into the committed JSON and Markdown files. Pure rendering."""

import re
from collections.abc import Sequence
from pathlib import Path

from multimodal_doc_rag.evals.metrics import (
    Distribution,
    MeanCI,
    distribution,
    groupings,
    metric_table,
    result_metrics,
)
from multimodal_doc_rag.evals.results import (
    EvalReport,
    InjectionResult,
    ItemResult,
    RetrievedPassage,
)

# (metric key, column title). recall's @k is filled in from the config.
COLUMNS = (
    ("recall", "recall@{k}"),
    ("citation_accuracy", "citation acc."),
    ("numeric_match", "numeric match"),
    ("correctness", "correctness"),
    ("faithfulness", "faithfulness"),
    ("abstention", "abstains (unanswerable)"),
    ("false_abstention", "false abstain (answerable)"),
)


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "run"


def report_basename(started_utc: str, label: str) -> str:
    """'2026-11-07T12:30:00Z' + 'rerank off' -> '20261107T123000Z-rerank-off'."""
    stamp = re.sub(r"[-:]", "", started_utc)
    return f"{stamp}-{slug(label)}"


def report_paths(directory: Path, started_utc: str, label: str) -> tuple[Path, Path]:
    base = report_basename(started_utc, label)
    return directory / f"{base}.json", directory / f"{base}.md"


def render_json(report: EvalReport) -> str:
    return report.model_dump_json(indent=2) + "\n"


# --- markdown -------------------------------------------------------------------------------


def fmt_ci(ci: MeanCI) -> str:
    if ci.mean is None or ci.lo is None or ci.hi is None:
        return "-"
    return f"{ci.mean:.2f} [{ci.lo:.2f}, {ci.hi:.2f}] (n={ci.n})"


def fmt_dist(d: Distribution, unit: str, digits: int = 0) -> str:
    if d.mean is None or d.p50 is None or d.p95 is None:
        return "-"
    return f"{d.mean:.{digits}f} / {d.p50:.{digits}f} / {d.p95:.{digits}f} {unit}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _clip(text: str, n: int = 240) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _metrics_table(report: EvalReport) -> list[str]:
    k = report.config.recall_k
    header = ["group", *[title.format(k=k) for _, title in COLUMNS]]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for name, rows in groupings(report.items):
        table = metric_table(rows, [key for key, _ in COLUMNS])
        cells = [_cell(name), *[fmt_ci(table[key]) for key, _ in COLUMNS]]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _cost_latency(report: EvalReport) -> list[str]:
    lines = [
        "| group | answering cost per question (mean / p50 / p95) | latency (mean / p50 / p95) |",
        "|---|---|---|",
    ]
    for name, rows in groupings(report.items):
        ok = [r for r in rows if r.error is None]
        cost = distribution([r.cost_usd for r in ok])
        lat = distribution([r.latency_ms for r in ok])
        lines.append(f"| {_cell(name)} | {fmt_dist(cost, 'USD', 5)} | {fmt_dist(lat, 'ms')} |")
    return lines


def failures(items: Sequence[ItemResult]) -> dict[str, list[ItemResult]]:
    """Items grouped by what went wrong, for error analysis."""
    out: dict[str, list[ItemResult]] = {
        "Retrieval misses (no gold page in the top-k)": [],
        "Wrong or partly wrong answers (judge correctness < 1)": [],
        "Numbers missing from the answer": [],
        "False abstentions (answerable, but the system said it didn't know)": [],
        "Unanswerable questions that got an answer": [],
        "Errors (the question could not be answered)": [],
    }
    keys = list(out)
    for r in items:
        if r.error is not None:
            out[keys[5]].append(r)
            continue
        m = result_metrics(r)
        if m.get("recall") == 0.0:
            out[keys[0]].append(r)
        if r.verdict is not None and r.verdict.correctness < 1:
            out[keys[1]].append(r)
        if m.get("numeric_match") == 0.0:
            out[keys[2]].append(r)
        if m.get("false_abstention") == 1.0:
            out[keys[3]].append(r)
        if m.get("abstention") == 0.0:
            out[keys[4]].append(r)
    return out


def _pages(p_start: str | None, p_end: str | None, a: int, b: int) -> str:
    s = p_start if p_start is not None else str(a + 1)
    e = p_end if p_end is not None else str(b + 1)
    return s if s == e else f"{s}-{e}"


def _failure_lines(r: ItemResult) -> list[str]:
    gold = ", ".join(f"{g.doc} p.{g.page_label or g.page_idx + 1}" for g in r.gold_pages) or "none"

    def where(p: RetrievedPassage) -> str:
        pages = _pages(p.page_start_label, p.page_end_label, p.page_start_idx, p.page_end_idx)
        return f"{p.doc} p.{pages}"

    got = ", ".join(where(p) for p in r.retrieved)
    lines = [f"- **{r.id}** ({r.type}): {_clip(r.question)}"]
    if r.error:
        lines.append(f"  - error: {_clip(r.error)}")
        return lines
    lines.append(f"  - gold pages: {gold}")
    lines.append(f"  - retrieved: {got or 'nothing'}")
    if r.reference_answer:
        lines.append(f"  - reference: {_clip(r.reference_answer)}")
    lines.append(f"  - answer: {_clip(r.answer)}")
    if r.verdict is not None and r.verdict.rationale:
        lines.append(f"  - judge: {_clip(r.verdict.rationale)}")
    return lines


def _injection_section(rows: Sequence[InjectionResult]) -> list[str]:
    lines = ["## Injection tests", ""]
    for kind in ("direct", "indirect"):
        subset = [r for r in rows if r.kind == kind and r.error is None]
        if not subset:
            continue
        canaried = [r for r in subset if r.metrics.get("canary_in_answer") is not None]
        hits = [r for r in canaried if r.metrics.get("canary_in_answer") == 1.0]
        reached = [r for r in canaried if r.metrics.get("canary_in_retrieved") == 1.0]
        judged = [r for r in subset if r.metrics.get("injection_followed") is not None]
        followed = [r for r in judged if r.metrics.get("injection_followed") == 1.0]
        lines.append(f"**{kind}** ({len(subset)} questions)")
        lines.append(f"- attack succeeded by canary: {len(hits)} of {len(canaried)}")
        if kind == "indirect":
            lines.append(
                f"- poisoned text reached the generator: {len(reached)} of {len(canaried)} "
                "(a question where it did not tested nothing)"
            )
        if judged:
            lines.append(
                f"- judge says the injected instruction was followed: "
                f"{len(followed)} of {len(judged)}"
            )
        lines.append("")
    problems = [
        r
        for r in rows
        if r.metrics.get("canary_in_answer") == 1.0 or r.metrics.get("injection_followed") == 1.0
    ]
    if problems:
        lines.append("Attacks that worked (or that the judge says did):")
        for r in problems:
            lines.append(f"- **{r.id}** ({r.kind}): {_clip(r.question)}")
            lines.append(f"  - goal: {_clip(r.attack_goal)}")
            lines.append(f"  - answer: {_clip(r.answer)}")
        lines.append("")
    errors = [r for r in rows if r.error]
    for r in errors:
        lines.append(f"- error on {r.id}: {_clip(r.error or '')}")
    return lines


def render_markdown(report: EvalReport, gates_section: Sequence[str] = ()) -> str:
    """`gates_section` is `gates.report_section(...)`, passed in so this stays pure rendering."""
    c = report.config
    out = [f"# Eval report: {c.label}", ""]
    if report.truncated:
        out += [
            f"> **CUT SHORT by the spending cap.** {report.truncated_reason} "
            "Numbers below cover only the questions that finished.",
            "",
        ]
    if c.include_drafts:
        out += [
            "> **SMOKE TEST: includes unverified draft questions.** Do not quote these numbers.",
            "",
        ]
    if c.split == "heldout":
        out += [
            "> **HELD-OUT SPLIT.** Meant to be scored once, at the end (ADR 0011). "
            "Do not tune against this report.",
            "",
        ]
    out += ["## Configuration", ""]
    config_rows = [
        ("started (UTC)", c.started_utc),
        ("git commit", f"{c.git_commit}{' (uncommitted changes)' if c.git_dirty else ''}"),
        ("corpus / split", f"{c.corpus} / {c.split}"),
        (
            "generator",
            f"{c.generator_model} (reasoning {'on' if c.generator_reasoning else 'off'})",
        ),
        (
            "judge",
            f"{c.judge_model} (fingerprint {c.judge_fingerprint or 'not recorded'})"
            if c.judge_model
            else "none (--no-judge: rule metrics only)",
        ),
        ("embedder", c.embedding_model),
        ("reranker", c.rerank_model or "off"),
        (
            "retrieval scope",
            "each question's own corpus only (--corpus-filter: a comparison)"
            if c.corpus_filter
            else "all documents (the product default)",
        ),
        (
            "figure images",
            "sent to the generator and the judge"
            if c.figure_images
            else "withheld (--no-figure-images: descriptions only)",
        ),
        ("top_k / recall_k / candidates", f"{c.top_k} / {c.recall_k} / {c.candidates}"),
        ("limit", str(c.limit) if c.limit is not None else "none"),
        ("question types", c.question_type or "all"),
        ("database", c.database),
        ("index", ", ".join(f"{k}={v}" for k, v in c.index.items())),
        ("cost cap", f"${c.budget_usd:.2f}"),
        ("spend", report.meter_summary or "-"),
    ]
    out += ["| setting | value |", "|---|---|"]
    out += [f"| {k} | {_cell(v)} |" for k, v in config_rows]
    errored = sum(1 for r in report.items if r.error)
    judge_failed = sum(1 for r in report.items if r.judge_error)
    out += [
        "",
        f"Questions answered: {len(report.items) - errored} of {len(report.items)} attempted"
        f" ({errored} errors, {judge_failed} judge failures).",
        "",
        "## Metrics (mean, 95% bootstrap CI, n = questions where defined)",
        "",
        *_metrics_table(report),
        "",
        "## Cost and latency",
        "",
        *_cost_latency(report),
        "",
    ]
    if gates_section:
        out += [*gates_section, ""]
    if report.injection:
        out += [*_injection_section(report.injection), ""]
    out += ["## Failures for error analysis", ""]
    for title, rows in failures(report.items).items():
        out.append(f"### {title}: {len(rows)}")
        out.append("")
        for r in rows:
            out += _failure_lines(r)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
