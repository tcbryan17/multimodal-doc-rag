"""Judge calibration (ADR 0011): how often does the LLM judge agree with the owner?

An LLM-judged score is only worth quoting if the judge is shown to agree with a human. The
owner grades ~30 answers WITHOUT seeing the judge's verdicts (otherwise they would anchor on
them), then we compare. Two numbers per dimension:
- raw agreement: the share of items where both gave the same grade;
- Cohen's kappa: agreement beyond what chance alone would produce. Raw agreement flatters a
  judge when one grade dominates (if 90% of answers are correct, a judge that always says
  "correct" agrees 90% of the time and has learned nothing).

Judge and owner must grade the SAME evidence. The judge is sent the figure images the
generator saw (ADR 0017), so `grade` exports those PNGs to a local folder and shows the path
next to each figure passage. Agreement measured on different evidence would mean nothing.
"""

import json
import random
from collections import Counter
from collections.abc import Callable, Hashable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from multimodal_doc_rag.evals.judge import JudgeVerdict
from multimodal_doc_rag.evals.metrics import stratified_sample
from multimodal_doc_rag.evals.results import EvalReport, ItemResult

DIMENSIONS = ("correctness", "faithfulness")
PASSAGE_CHARS = 1200  # how much of each passage the grader sees


class CalibrationError(ValueError):
    pass


class Grade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correctness: float  # 0, 0.5 or 1
    faithfulness: int  # 0 or 1


class ShownPassage(BaseModel):
    doc: str
    pages: str
    content: str
    # Set when the generator (and the judge) were sent this figure passage's image: the chunk
    # id to fetch the same PNG by, for the hand-grader.
    figure_chunk_id: int | None = None


class CalibrationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    corpus: str
    type: str
    question: str
    answerable: bool
    reference_answer: str | None
    answer: str
    passages: list[ShownPassage]
    human: Grade | None = None  # filled in by `grade`
    # Kept LAST and never displayed by `grade`. It lives in the same file only for
    # convenience; do not open the file in an editor while you are grading.
    judge: Grade


# --- sampling and storage -------------------------------------------------------------------


def _pages(start_label: str | None, end_label: str | None, start_idx: int, end_idx: int) -> str:
    s = start_label if start_label is not None else str(start_idx + 1)
    e = end_label if end_label is not None else str(end_idx + 1)
    return s if s == e else f"{s}-{e}"


def entry_from_result(r: ItemResult, verdict: JudgeVerdict) -> CalibrationEntry:
    return CalibrationEntry(
        id=r.id,
        corpus=r.corpus,
        type=r.type,
        question=r.question,
        answerable=r.answerable,
        reference_answer=r.reference_answer,
        # The judged text, whose [n] markers match the passage numbering shown below.
        answer=r.judged_answer if r.judged_answer is not None else r.answer,
        passages=[
            ShownPassage(
                doc=p.doc,
                pages=_pages(
                    p.page_start_label, p.page_end_label, p.page_start_idx, p.page_end_idx
                ),
                content=p.content,
                figure_chunk_id=p.chunk_id if p.image_sent else None,
            )
            for p in r.retrieved
        ],
        judge=Grade(correctness=verdict.correctness, faithfulness=verdict.faithfulness),
    )


def sample_entries(report: EvalReport, n: int, seed: int = 0) -> list[CalibrationEntry]:
    """A seeded sample of the report's judged items, spread across corpus × type ×
    answerable so every kind of question is represented."""
    strata: dict[str, list[ItemResult]] = {}
    for r in report.items:
        if r.error is None and r.verdict is not None:
            strata.setdefault(f"{r.corpus}/{r.type}/{r.answerable}", []).append(r)
    if not strata:
        raise CalibrationError(
            "the report has no judged items to sample (was it a --no-judge run?)"
        )
    picked = stratified_sample(strata, n, random.Random(seed))
    return [
        entry_from_result(r, r.verdict) for r in sorted(picked, key=lambda r: r.id) if r.verdict
    ]


def save_entries(path: Path, entries: Sequence[CalibrationEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e.model_dump(mode="json"), ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )


def load_entries(path: Path) -> list[CalibrationEntry]:
    if not path.exists():
        raise CalibrationError(f"{path} does not exist; run `calibrate_judge.py sample` first")
    out: list[CalibrationEntry] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                out.append(CalibrationEntry.model_validate_json(line))
            except ValidationError as exc:
                raise CalibrationError(f"{path}:{n}: {exc}") from exc
    return out


# --- grading by hand ------------------------------------------------------------------------

Ask = Callable[[str], str]
Say = Callable[[str], None]


def parse_correctness(text: str) -> float | None:
    return {"0": 0.0, "0.5": 0.5, ".5": 0.5, "1": 1.0}.get(text.strip())


def parse_faithfulness(text: str) -> int | None:
    return {"0": 0, "1": 1}.get(text.strip())


def figure_ids(entries: Sequence[CalibrationEntry]) -> list[int]:
    """Chunk ids of every figure image the judge saw for these entries (sorted, unique)."""
    return sorted(
        {p.figure_chunk_id for e in entries for p in e.passages if p.figure_chunk_id is not None}
    )


def export_figures(
    entries: Sequence[CalibrationEntry], pngs: Mapping[int, bytes], directory: Path
) -> dict[int, Path]:
    """Write the figure images the judge saw to `directory/<chunk_id>.png` so the owner can
    open them while grading. Raises if any is missing: grading without an image the judge had
    would compare two different tasks."""
    missing = [cid for cid in figure_ids(entries) if cid not in pngs]
    if missing:
        raise CalibrationError(
            f"no image in the database for figure chunk(s) {missing}. Was the index "
            "re-ingested since the run? Sample from a newer report, or point --database-url "
            "at the database the run used."
        )
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[int, Path] = {}
    for cid in figure_ids(entries):
        paths[cid] = directory / f"{cid}.png"
        paths[cid].write_bytes(pngs[cid])
    return paths


def show_entry(
    e: CalibrationEntry,
    say: Say,
    position: str,
    figure_paths: Mapping[int, Path] | None = None,
) -> None:
    """What the owner sees. Deliberately omits `judge`."""
    say("")
    say(f"=== {e.id} {position}")
    say(f"Question:  {e.question}")
    say(f"Reference: {e.reference_answer or '(none: the documents do NOT answer this question)'}")
    say("--- passages the system was shown ---")
    for n, p in enumerate(e.passages, start=1):
        text = " ".join(p.content.split())
        clipped = text if len(text) <= PASSAGE_CHARS else text[:PASSAGE_CHARS] + "…"
        say(f"[{n}] {p.doc} p.{p.pages}: {clipped}")
        if p.figure_chunk_id is not None:
            path = (figure_paths or {}).get(p.figure_chunk_id)
            say(
                f"    FIGURE IMAGE (the system and the judge saw it; open it before grading): "
                f"{path if path is not None else 'NOT EXPORTED'}"
            )
    say("--- the system's answer ---")
    say(e.answer)
    say("---")


def grade_loop(
    entries: Sequence[CalibrationEntry],
    ask: Ask,
    say: Say,
    save: Callable[[Sequence[CalibrationEntry]], None],
    figure_paths: Mapping[int, Path] | None = None,
) -> int:
    """Collect the owner's grades for entries not yet graded; saves after each. 'q' quits.
    Returns how many were graded this session."""
    current = list(entries)
    todo = [e for e in current if e.human is None]
    graded = 0
    for n, entry in enumerate(todo, start=1):
        show_entry(entry, say, f"[{n}/{len(todo)}]", figure_paths)
        correctness: float | None = None
        while correctness is None:
            raw = ask("correctness 0 / 0.5 / 1 (q to quit) > ")
            if raw.strip().lower() == "q":
                return graded
            correctness = parse_correctness(raw)
        faithfulness: int | None = None
        while faithfulness is None:
            raw = ask("faithfulness 0 (a claim is unsupported) / 1 (all supported) > ")
            if raw.strip().lower() == "q":
                return graded
            faithfulness = parse_faithfulness(raw)
        grade = Grade(correctness=correctness, faithfulness=faithfulness)
        current = [
            e.model_copy(update={"human": grade}) if e.id == entry.id else e for e in current
        ]
        save(current)
        graded += 1
    return graded


# --- agreement ------------------------------------------------------------------------------


def raw_agreement(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("need two equal-length, non-empty grade lists")
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def cohens_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float | None:
    """Cohen's kappa = (p_o - p_e) / (1 - p_e).

    p_o is the observed agreement. p_e is the agreement expected if each rater graded at
    random with their own grade frequencies: sum over grades of (share of a) * (share of b).
    1 = perfect, 0 = no better than chance, negative = worse than chance. Returns None when
    p_e == 1 (both raters always gave the same single grade): kappa is undefined there.
    """
    p_o = raw_agreement(a, b)
    n = len(a)
    ca, cb = Counter(a), Counter(b)
    p_e = sum((ca[g] / n) * (cb[g] / n) for g in set(ca) | set(cb))
    if p_e == 1.0:
        return None
    return (p_o - p_e) / (1 - p_e)


def confusion(
    judge: Sequence[Hashable], human: Sequence[Hashable]
) -> dict[tuple[Hashable, Hashable], int]:
    """Counts of (judge grade, human grade) pairs."""
    return dict(Counter(zip(judge, human, strict=True)))


class DimensionAgreement(BaseModel):
    n: int
    raw: float
    kappa: float | None
    confusion: list[tuple[str, str, int]]  # (judge grade, human grade, count), sorted


class AgreementReport(BaseModel):
    n_graded: int
    dimensions: dict[str, DimensionAgreement]


def agreement(entries: Sequence[CalibrationEntry]) -> AgreementReport:
    graded = [e for e in entries if e.human is not None]
    if not graded:
        raise CalibrationError("no human grades yet; run `calibrate_judge.py grade` first")
    dims: dict[str, DimensionAgreement] = {}
    for dim in DIMENSIONS:
        judge = [getattr(e.judge, dim) for e in graded]
        human = [getattr(e.human, dim) for e in graded if e.human]
        pairs = sorted(confusion(judge, human).items(), key=lambda kv: (kv[0][0], kv[0][1]))
        dims[dim] = DimensionAgreement(
            n=len(graded),
            raw=raw_agreement(judge, human),
            kappa=cohens_kappa(judge, human),
            confusion=[(f"{j:g}", f"{h:g}", c) for (j, h), c in pairs],
        )
    return AgreementReport(n_graded=len(graded), dimensions=dims)


def interpret_kappa(kappa: float | None) -> str:
    """Landis & Koch (1977) verbal bands; a convention, not a law."""
    if kappa is None:
        return "undefined (one grade only)"
    for limit, word in ((0.0, "worse than chance"), (0.2, "slight"), (0.4, "fair"),
                        (0.6, "moderate"), (0.8, "substantial")):  # fmt: skip
        if kappa <= limit:
            return word
    return "almost perfect"


def render_summary(report: AgreementReport, judge_model: str | None = None) -> str:
    lines = ["## Judge calibration", ""]
    who = f" (judge: {judge_model})" if judge_model else ""
    lines.append(
        f"The owner hand-graded {report.n_graded} answers without seeing the judge's verdicts{who}."
    )
    lines += ["", "| dimension | n | raw agreement | Cohen's kappa |", "|---|---|---|---|"]
    for dim, d in report.dimensions.items():
        kappa = "undefined" if d.kappa is None else f"{d.kappa:.2f} ({interpret_kappa(d.kappa)})"
        lines.append(f"| {dim} | {d.n} | {d.raw:.0%} | {kappa} |")
    for dim, d in report.dimensions.items():
        lines += ["", f"Confusion for {dim} (rows: judge, columns: human):", ""]
        human_grades = sorted({h for _, h, _ in d.confusion}, key=float)
        judge_grades = sorted({j for j, _, _ in d.confusion}, key=float)
        counts = {(j, h): c for j, h, c in d.confusion}
        lines.append("| judge \\ human | " + " | ".join(human_grades) + " |")
        lines.append("|---|" + "---|" * len(human_grades))
        for j in judge_grades:
            lines.append(
                f"| {j} | " + " | ".join(str(counts.get((j, h), 0)) for h in human_grades) + " |"
            )
    return "\n".join(lines) + "\n"
