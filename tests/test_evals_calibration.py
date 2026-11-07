"""Judge calibration: sampling, blind grading, kappa (checked against hand arithmetic)."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from multimodal_doc_rag.evals.calibration import (
    CalibrationEntry,
    CalibrationError,
    Grade,
    ShownPassage,
    agreement,
    cohens_kappa,
    confusion,
    grade_loop,
    interpret_kappa,
    load_entries,
    parse_correctness,
    parse_faithfulness,
    raw_agreement,
    render_summary,
    sample_entries,
    save_entries,
    show_entry,
)
from multimodal_doc_rag.evals.judge import JudgeVerdict
from multimodal_doc_rag.evals.results import EvalReport, ItemResult, RetrievedPassage, RunConfig


def test_kappa_matches_a_hand_computed_example() -> None:
    # 10 items. judge: 1 1 1 0 0 0 1 0 1 1   human: 1 1 0 0 0 1 1 0 1 1
    judge = [1, 1, 1, 0, 0, 0, 1, 0, 1, 1]
    human = [1, 1, 0, 0, 0, 1, 1, 0, 1, 1]
    # agree on 8 of 10 -> p_o = 0.8
    # judge says 1 six times and 0 four times; so does the human -> p_e = .6*.6 + .4*.4 = 0.52
    # kappa = (0.8 - 0.52) / (1 - 0.52) = 0.28 / 0.48 = 0.58333...
    assert raw_agreement(judge, human) == 0.8
    assert cohens_kappa(judge, human) == pytest.approx(0.28 / 0.48)


def test_kappa_edge_cases() -> None:
    assert cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == pytest.approx(1.0)
    assert cohens_kappa([1, 1, 1], [1, 1, 1]) is None  # one grade only: undefined
    assert cohens_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == pytest.approx(-1.0)
    # The "always correct" judge: 90% raw agreement, kappa of zero.
    human = [1] * 9 + [0]
    assert raw_agreement([1] * 10, human) == 0.9
    assert cohens_kappa([1] * 10, human) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        raw_agreement([1], [1, 0])
    with pytest.raises(ValueError):
        raw_agreement([], [])


def test_kappa_three_levels() -> None:
    judge = [0, 0.5, 1, 1, 0.5, 0]
    human = [0, 0.5, 1, 0.5, 0.5, 1]
    # agree on items 1,2,3,5 -> p_o = 4/6; each grade has marginal 2/6 for the judge;
    # human: 0 -> 1/6, 0.5 -> 3/6, 1 -> 2/6. p_e = (2*1 + 2*3 + 2*2)/36 = 12/36 = 1/3.
    assert cohens_kappa(judge, human) == pytest.approx((4 / 6 - 1 / 3) / (1 - 1 / 3))


def test_confusion_counts() -> None:
    assert confusion([1, 1, 0], [1, 0, 0]) == {(1, 1): 1, (1, 0): 1, (0, 0): 1}


def test_interpret_kappa_bands() -> None:
    assert interpret_kappa(None).startswith("undefined")
    assert interpret_kappa(-0.1) == "worse than chance"
    assert interpret_kappa(0.58) == "moderate"
    assert interpret_kappa(0.85) == "almost perfect"


def test_parsers() -> None:
    assert parse_correctness(" .5 ") == 0.5 and parse_correctness("1") == 1.0
    assert parse_correctness("2") is None and parse_correctness("") is None
    assert parse_faithfulness("0") == 0 and parse_faithfulness("0.5") is None


def result(
    id: str, correctness: float | None, corpus: str = "faa", type_: str = "fact"
) -> ItemResult:
    verdict = (
        None
        if correctness is None
        else JudgeVerdict(correctness=correctness, faithfulness=1, rationale="SECRET RATIONALE")
    )
    return ItemResult(
        id=id, corpus=corpus, split="dev", type=type_, question=f"Q {id}", answerable=True,
        reference_answer="ref", gold_pages=[], answer=f"A {id}", verdict=verdict,
        retrieved=[RetrievedPassage(
            chunk_id=1, doc="d1", kind="text", page_start_idx=0, page_end_idx=1,
            page_start_label="8-1", page_end_label=None, score=1.0, content="passage text",
        )],
    )  # fmt: skip


def report_of(items: Sequence[ItemResult]) -> EvalReport:
    cfg = RunConfig(
        label="t", started_utc="2026-11-07T00:00:00Z", git_commit="x", git_dirty=False,
        corpus="all", split="dev", generator_model="a/b", judge_model="c/d",
        embedding_model="e", rerank_model=None, top_k=5, recall_k=5, candidates=30,
        budget_usd=1.0, include_drafts=False, limit=None, index={}, database="rag_test",
    )  # fmt: skip
    return EvalReport(config=cfg, items=list(items))


def test_sample_entries_is_seeded_stratified_and_skips_unjudged() -> None:
    items = [result(f"a{i}", 1.0) for i in range(10)]
    items += [result(f"b{i}", 0.5, corpus="10k") for i in range(10)]
    items += [result("skip", None), result("err", 1.0)]
    items[-1].error = "boom"
    rep = report_of(items)
    a = sample_entries(rep, 6, seed=1)
    assert a == sample_entries(rep, 6, seed=1)
    assert len(a) == 6 and {e.corpus for e in a} == {"faa", "10k"}
    assert "skip" not in {e.id for e in a} and "err" not in {e.id for e in a}
    assert a[0].passages[0].pages == "8-1-2"  # start label "8-1", end idx 1 -> "2"
    with pytest.raises(CalibrationError, match="no-judge"):
        sample_entries(report_of([result("x", None)]), 3)


def entry(id: str, judge: float, human: float | None = None) -> CalibrationEntry:
    return CalibrationEntry(
        id=id, corpus="faa", type="fact", question="Q?", answerable=True, reference_answer="r",
        answer="the answer",
        passages=[ShownPassage(doc="d", pages="1", content="p " * 800)],
        human=None if human is None else Grade(correctness=human, faithfulness=1),
        judge=Grade(correctness=judge, faithfulness=1),
    )  # fmt: skip


def test_grading_view_never_shows_judge_verdicts() -> None:
    shown: list[str] = []
    show_entry(entry("e1", judge=0.5), shown.append, "[1/1]")
    text = "\n".join(shown)
    assert "Q?" in text and "the answer" in text and "…" in text  # long passage is clipped
    assert "judge" not in text.lower() and "0.5" not in text


def test_grade_loop_resumes_saves_and_reprompts() -> None:
    entries = [entry("e1", 1.0), entry("e2", 0.0, human=0.0), entry("e3", 0.5)]
    answers = ["7", "1", "x", "1", "0.5", "q"]  # e1: bad, 1, bad, 1 ; e3: 0.5 then quit
    prompts: list[str] = []

    def ask(p: str) -> str:
        prompts.append(p)
        return answers.pop(0)

    saved: list[list[CalibrationEntry]] = []
    n = grade_loop(entries, ask, lambda _m: None, lambda cur: saved.append(list(cur)))
    assert n == 1  # e2 was already graded and is skipped; e3 was abandoned at faithfulness
    assert saved[0][0].human == Grade(correctness=1.0, faithfulness=1)
    assert saved[0][2].human is None


def test_file_round_trip_and_summary(tmp_path: Path) -> None:
    path = tmp_path / "cal.jsonl"
    entries = [entry("a", 1.0, 1.0), entry("b", 1.0, 0.0), entry("c", 0.0, 0.0), entry("d", 0.0)]
    save_entries(path, entries)
    assert load_entries(path) == entries
    rep = agreement(load_entries(path))
    assert rep.n_graded == 3  # "d" has no human grade yet
    c = rep.dimensions["correctness"]
    assert c.raw == pytest.approx(2 / 3)
    assert ("1", "0", 1) in c.confusion
    # faithfulness: both always said 1 -> kappa undefined
    assert rep.dimensions["faithfulness"].kappa is None
    md = render_summary(rep, judge_model="google/gemma")
    assert "hand-graded 3 answers" in md and "google/gemma" in md
    assert "67%" in md and "undefined" in md and "judge \\ human" in md


def test_agreement_needs_grades_and_missing_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(CalibrationError, match="grade"):
        agreement([entry("a", 1.0)])
    with pytest.raises(CalibrationError, match="sample"):
        load_entries(tmp_path / "nope.jsonl")
