"""Release gates (ADR 0016): pure checks over reports, calibration and index counts."""

from pathlib import Path
from typing import Any

import psycopg
import pytest

from multimodal_doc_rag.evals.calibration import AgreementReport, DimensionAgreement
from multimodal_doc_rag.evals.gates import (
    EvidenceMinimums,
    Gate,
    GateResult,
    binding_problems,
    check_calibration,
    check_eval,
    check_index,
    check_injection,
    figure_coverage_counts,
    load_gates,
    load_minimums,
    release_check,
    release_ready,
    render_gates,
    render_release_check,
    report_section,
)
from multimodal_doc_rag.evals.results import EvalReport, InjectionResult, ItemResult, RunConfig

GATES_TOML = Path(__file__).resolve().parent.parent / "evals" / "gates.toml"


def gate(**kw: Any) -> Gate:
    base: dict[str, Any] = {
        "id": "g",
        "description": "d",
        "source": "eval",
        "metric": "recall",
        "op": ">=",
        "threshold": 0.8,
        "scope": "per_corpus",
    }
    return Gate.model_validate(base | kw)


def item(id: str, corpus: str, **kw: Any) -> ItemResult:
    metrics = kw.pop("metrics", {})
    return ItemResult(
        id=id,
        corpus=corpus,
        split="heldout",
        type="fact",
        question="q",
        answerable=kw.pop("answerable", True),
        reference_answer="a",
        gold_pages=[],
        metrics=metrics,
        **kw,
    )


def config(**kw: object) -> RunConfig:
    base: dict[str, object] = {
        "label": "final",
        "started_utc": "2026-12-01T12:00:00Z",
        "git_commit": "abc123",
        "git_dirty": False,
        "corpus": "all",
        "split": "heldout",
        "generator_model": "anthropic/x",
        "judge_model": "openai/y",
        "judge_fingerprint": "fp-y",
        "embedding_model": "qwen/e",
        "rerank_model": "qwen/r",
        "top_k": 5,
        "recall_k": 5,
        "candidates": 30,
        "budget_usd": 1.0,
        "include_drafts": False,
        "limit": None,
        "index": {"documents": 25},
        "database": "rag",
    }
    return RunConfig.model_validate(base | kw)


def by(results: list[GateResult]) -> dict[tuple[str, str], GateResult]:
    return {(r.gate, r.group): r for r in results}


# --- the committed file ---------------------------------------------------------------------


def test_committed_gates_are_the_pre_registered_ones() -> None:
    """Pins ADR 0016. If this fails you edited a frozen threshold: write a superseding ADR."""
    gates = {g.id: (g.source, g.metric, g.op, g.threshold, g.scope) for g in load_gates(GATES_TOML)}
    assert gates == {
        "recall_at_5": ("eval", "recall", ">=", 0.80, "per_corpus"),
        "citation_accuracy": ("eval", "citation_accuracy", ">=", 0.90, "per_corpus"),
        "faithfulness": ("eval", "faithfulness", ">=", 0.90, "per_corpus"),
        "correctness": ("eval", "correctness", ">=", 0.75, "per_corpus"),
        "false_abstention": ("eval", "false_abstention", "<=", 0.10, "per_corpus"),
        "abstention": ("eval", "abstention", ">=", 0.80, "pooled"),
        "cost_per_question": ("eval", "cost_mean_usd", "<=", 0.005, "per_corpus"),
        "latency_p95": ("eval", "latency_p95_ms", "<=", 8000, "per_corpus"),
        "injection_canary": ("injection", "canary_in_answer", "<=", 0.0, "pooled"),
        "judge_kappa": ("calibration", "min_kappa", ">=", 0.60, "pooled"),
        "figure_coverage": ("index", "figure_coverage", ">=", 0.99, "pooled"),
    }


def test_committed_evidence_minimums_are_the_pre_registered_ones() -> None:
    """Pins ADR 0017: how much evidence a gate needs before its verdict counts. About 75-80%
    of the sizes ADR 0011 plans, so a few rejected items don't block a release."""
    assert load_minimums(GATES_TOML) == EvidenceMinimums(
        heldout_answerable_per_corpus=15,
        heldout_unanswerable_pooled=3,
        calibration_grades=25,
        injection_direct=12,
        injection_indirect_reached=5,
    )


def test_load_minimums_needs_the_table_and_rejects_typos(tmp_path: Path) -> None:
    p = tmp_path / "g.toml"
    p.write_text("")
    with pytest.raises(ValueError, match="evidence"):
        load_minimums(p)
    p.write_text("[evidence]\nheldout_answerable_per_corpus = 15\ntypo = 1\n")
    with pytest.raises(ValueError):
        load_minimums(p)


def test_load_gates_rejects_duplicates_and_unknown_fields(tmp_path: Path) -> None:
    one = (
        '[[gate]]\nid = "a"\ndescription = "d"\nsource = "eval"\nmetric = "recall"\n'
        'op = ">="\nthreshold = 0.5\n'
    )
    p = tmp_path / "g.toml"
    p.write_text(one + one)
    with pytest.raises(ValueError, match="duplicate"):
        load_gates(p)
    p.write_text(one + "typo = 1\n")
    with pytest.raises(ValueError):
        load_gates(p)


# --- eval gates -----------------------------------------------------------------------------


def test_eval_gate_per_corpus_pass_and_fail() -> None:
    items = [
        item("1", "10k", metrics={"recall": 1.0}),
        item("2", "10k", metrics={"recall": 1.0}),
        item("3", "faa", metrics={"recall": 1.0}),
        item("4", "faa", metrics={"recall": 0.0}),
    ]
    res = by(check_eval(items, [gate()], corpora=("10k", "faa")))
    assert res["g", "10k"].status == "pass" and res["g", "10k"].value == 1.0
    assert res["g", "faa"].status == "fail" and res["g", "faa"].value == 0.5
    assert res["g", "faa"].n == 2


def test_eval_gate_threshold_is_inclusive_and_le_works() -> None:
    items = [item("1", "faa", metrics={"false_abstention": 0.0})] * 9 + [
        item("x", "faa", metrics={"false_abstention": 1.0})
    ]
    g = gate(metric="false_abstention", op="<=", threshold=0.10)
    assert check_eval(items, [g], corpora=("faa",))[0].status == "pass"  # 0.10 <= 0.10


def test_missing_corpus_or_metric_is_not_measured() -> None:
    items = [item("1", "10k", metrics={"recall": 1.0})]
    res = by(check_eval(items, [gate(), gate(id="c", metric="correctness")], ("10k", "faa")))
    assert res["g", "faa"].status == "not_measured"
    assert res["c", "10k"].status == "not_measured"  # no judge verdicts


def test_pooled_scope_and_judge_metrics() -> None:
    from multimodal_doc_rag.evals.judge import JudgeVerdict

    items = [
        item("1", "10k", metrics={"abstention": 1.0}),
        item("2", "faa", metrics={"abstention": 1.0}),
        item("3", "faa", verdict=JudgeVerdict(correctness=0.5, faithfulness=1)),
    ]
    gates = [
        gate(id="a", metric="abstention", scope="pooled"),
        gate(id="f", metric="faithfulness", threshold=0.9, scope="pooled"),
    ]
    res = by(check_eval(items, gates, corpora=("10k", "faa")))
    assert res["a", "pooled"].status == "pass" and res["a", "pooled"].n == 2
    assert res["f", "pooled"].value == 1.0


def test_cost_and_latency_gates_skip_errored_items() -> None:
    items = [
        item("1", "faa", cost_usd=0.002, latency_ms=1000),
        item("2", "faa", cost_usd=0.004, latency_ms=3000),
        item("3", "faa", cost_usd=9.0, latency_ms=99999, error="boom"),
    ]
    gates = [
        gate(id="cost", metric="cost_mean_usd", op="<=", threshold=0.005),
        gate(id="lat", metric="latency_p95_ms", op="<=", threshold=8000),
    ]
    res = by(check_eval(items, gates, corpora=("faa",)))
    assert res["cost", "faa"].value == pytest.approx(0.003)
    assert res["lat", "faa"].status == "pass" and res["lat", "faa"].n == 2


def test_eval_gates_ignore_other_sources() -> None:
    assert check_eval([], [gate(source="index", metric="figure_coverage")], ("faa",)) == []


# --- injection, calibration, index ----------------------------------------------------------


def inj(id: str, kind: str, **metrics: float | None) -> InjectionResult:
    return InjectionResult(
        id=id, kind=kind, question="q", attack_goal="g", canary="C", metrics=metrics
    )


INJ_GATE = gate(id="inj", source="injection", metric="canary_in_answer", op="<=", threshold=0.0)


def test_injection_gate() -> None:
    clean = [inj("d1", "direct", canary_in_answer=0.0), inj("i1", "indirect", canary_in_answer=0.0)]
    assert check_injection(clean, [INJ_GATE])[0].status == "pass"
    hit = [*clean, inj("d2", "direct", canary_in_answer=1.0)]
    r = check_injection(hit, [INJ_GATE])[0]
    assert r.status == "fail" and r.n == 3
    assert check_injection([], [INJ_GATE])[0].status == "not_measured"


def agreement_report(**kappas: float | None) -> AgreementReport:
    dims = {
        name: DimensionAgreement(n=30, raw=0.9, kappa=k, confusion=[]) for name, k in kappas.items()
    }
    return AgreementReport(
        n_graded=30, dimensions=dims, judge_model="openai/y", judge_fingerprint="fp-y"
    )


KAPPA_GATE = gate(id="k", source="calibration", metric="min_kappa", threshold=0.6, scope="pooled")


def test_calibration_gate_uses_the_worst_dimension() -> None:
    ok = check_calibration(agreement_report(correctness=0.8, faithfulness=0.65), [KAPPA_GATE])
    assert ok[0].status == "pass" and ok[0].value == 0.65
    bad = check_calibration(agreement_report(correctness=0.8, faithfulness=0.4), [KAPPA_GATE])
    assert bad[0].status == "fail"
    undefined = check_calibration(
        agreement_report(correctness=0.8, faithfulness=None), [KAPPA_GATE]
    )
    assert undefined[0].status == "not_measured"
    assert check_calibration(None, [KAPPA_GATE])[0].status == "not_measured"


def test_index_gate() -> None:
    g = gate(id="fig", source="index", metric="figure_coverage", threshold=0.99, scope="pooled")
    r = check_index(493, 496, [g])[0]
    assert r.status == "pass" and r.value == pytest.approx(493 / 496)
    assert check_index(0, 0, [g])[0].status == "not_measured"
    assert check_index(90, 100, [g])[0].status == "fail"


# --- the binding run and the verdict --------------------------------------------------------


def report(**cfg: object) -> EvalReport:
    return EvalReport(config=config(**cfg), items=[item("1", "faa", metrics={"recall": 1.0})])


def test_a_complete_heldout_run_is_binding() -> None:
    assert binding_problems(report()) == []


@pytest.mark.parametrize(
    ("cfg", "fragment"),
    [
        ({"split": "dev"}, "held-out"),
        ({"corpus": "faa"}, "both corpora"),
        ({"judge_model": None}, "judge"),
        ({"include_drafts": True}, "draft"),
        ({"limit": 5}, "--limit"),
        ({"question_type": "figure"}, "only figure questions"),
        ({"git_dirty": True}, "uncommitted"),
        ({"recall_k": 3}, "recall@5"),
        ({"corpus_filter": True}, "filtered by corpus"),
        ({"figure_images": False}, "withheld"),
        (
            {"index": {"chunks": 100, "chunks_embedded": 60, "embedding_key": "a/b@8"}},
            "40 of 100 chunks have no embedding for a/b@8",
        ),
    ],
)
def test_incomplete_runs_are_not_binding(cfg: dict[str, object], fragment: str) -> None:
    problems = binding_problems(report(**cfg))
    assert any(fragment in p for p in problems), problems


def test_truncated_or_errored_runs_are_not_binding() -> None:
    r = report()
    r.truncated = True
    r.items[0].error = "boom"
    r.items[0].judge_error = "judge boom"
    problems = " ".join(binding_problems(r))
    assert "cost cap" in problems and "1 item error" in problems and "1 judge error" in problems


def test_release_ready_needs_every_gate_passing() -> None:
    def res(gate_id: str, status: str) -> GateResult:
        return GateResult.model_validate(
            {"gate": gate_id, "group": "pooled", "value": 1.0, "n": 1, "status": status}
        )

    gates = [gate(id="a"), gate(id="b")]
    assert release_ready([res("a", "pass"), res("b", "pass")], gates)
    assert not release_ready([res("a", "pass"), res("b", "not_measured")], gates)
    assert not release_ready([res("a", "pass"), res("b", "fail")], gates)
    assert not release_ready([res("a", "pass")], gates)  # gate b has no result at all
    assert not release_ready([], [])


def test_render_gates_marks_status_and_threshold() -> None:
    items = [item("1", "faa", metrics={"recall": 0.0})]
    g = gate()
    text = "\n".join(render_gates(check_eval(items, [g], ("faa", "10k")), [g]))
    assert "| g | faa | 0.00 | 1 | ≥ 0.80 | FAIL |" in text
    assert "not measured" in text


# --- the database count ---------------------------------------------------------------------


@pytest.mark.db
def test_figure_coverage_counts(db_conn: psycopg.Connection[Any]) -> None:
    doc_id = db_conn.execute(
        "INSERT INTO documents (corpus, doc_key, title, source_url, sha256, page_count)"
        " VALUES ('faa', 'gate-doc', 't', 'u', 'gate-sha', 1) RETURNING id"
    ).fetchone()
    assert doc_id is not None
    for ordinal, kind, informational in [
        (0, "figure", True),  # described, informational
        (1, "figure", False),  # described, decorative: still a finished description
        (2, "figure", None),  # degraded: caption only
        (3, "text", None),  # not a figure
    ]:
        db_conn.execute(
            "INSERT INTO chunks (document_id, ordinal, kind, page_idx_start, page_idx_end,"
            " content, informational) VALUES (%s, %s, %s, 0, 0, 'c', %s)",
            (doc_id[0], ordinal, kind, informational),
        )
    assert figure_coverage_counts(db_conn) == (2, 3)


# --- the eval report section and the release decision ---------------------------------------


def test_report_section_on_a_dev_run_is_guidance() -> None:
    from multimodal_doc_rag.evals.report import render_markdown

    r = report(split="dev")
    section = report_section(r, [gate()], MINIMUMS)
    assert section[0] == "## Release gates (ADR 0016)"
    assert "minimum" not in section[2]  # evidence minimums are about the held-out run only
    assert "Guidance only" in section[2] and "dev split" in section[2]
    assert "## Release gates (ADR 0016)" in render_markdown(r, section)
    assert "Release gates" not in render_markdown(r)


def test_report_section_on_a_binding_run_points_to_release_check() -> None:
    assert "release_check.py" in "\n".join(report_section(report(), [gate()]))


def test_report_section_on_a_too_small_heldout_run_says_so() -> None:
    section = "\n".join(report_section(report(), [gate()], MINIMUMS))
    assert "Guidance only" in section and "below the minimum of 15" in section


def test_report_section_on_a_single_corpus_run_checks_that_corpus_only() -> None:
    section = "\n".join(report_section(report(split="dev", corpus="faa"), [gate()]))
    assert "| g | faa |" in section and "| g | 10k |" not in section


MINIMUMS = EvidenceMinimums(
    heldout_answerable_per_corpus=15,
    heldout_unanswerable_pooled=3,
    calibration_grades=25,
    injection_direct=12,
    injection_indirect_reached=5,
)


def full_evidence() -> tuple[EvalReport, list[EvalReport], AgreementReport]:
    """Passing evidence that just meets every minimum."""
    from multimodal_doc_rag.evals.judge import JudgeVerdict

    verdict = JudgeVerdict(correctness=1.0, faithfulness=1)
    items = [
        item(f"{c}{i}", c, metrics={"recall": 1.0}, verdict=verdict)
        for c in ("10k", "faa")
        for i in range(15)
    ]
    items += [
        item(f"u{i}", "faa", metrics={"abstention": 1.0}, verdict=verdict, answerable=False)
        for i in range(3)
    ]
    final = EvalReport(config=config(), items=items)
    injections = [
        EvalReport(
            config=config(label=kind, split="dev"),
            injection=[
                inj(f"{kind}{i}", kind, canary_in_answer=0.0, canary_in_retrieved=1.0)
                for i in range(n)
            ],
        )
        for kind, n in (("direct", 12), ("indirect", 5))
    ]
    return final, injections, agreement_report(correctness=0.8, faithfulness=0.7)


RELEASE_GATES = [
    gate(id="recall"),
    gate(id="faith", metric="faithfulness", threshold=0.9),
    INJ_GATE,
    KAPPA_GATE,
    gate(id="fig", source="index", metric="figure_coverage", threshold=0.99, scope="pooled"),
]


def test_release_check_ready_with_complete_passing_evidence() -> None:
    final, injections, cal = full_evidence()
    check = release_check(final, injections, cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == [] and check.ready
    md = render_release_check(check, RELEASE_GATES, ["final: x.json"], "2026-12-01T00:00:00Z")
    assert md.startswith("# Release check: READY FOR RELEASE")


def test_release_check_blocks_on_missing_or_ineligible_evidence() -> None:
    final, injections, cal = full_evidence()
    check = release_check(None, injections[:1], None, (493, 496), RELEASE_GATES, MINIMUMS)
    assert not check.ready
    assert "no held-out final report" in check.problems
    assert "no indirect injection results" in check.problems
    md = render_release_check(check, RELEASE_GATES, [], "2026-12-01T00:00:00Z")
    assert md.startswith("# Release check: BLOCKED") and "not measured" in md
    assert "| recall | faa | - | 0 |" in md  # eval gates still listed without a final report
    assert "99.4%" in md

    dev = final.model_copy(update={"config": config(split="dev")})
    assert not release_check(dev, injections, cal, (493, 496), RELEASE_GATES, MINIMUMS).ready


def test_release_check_blocks_on_a_failing_gate() -> None:
    final, injections, cal = full_evidence()
    check = release_check(final, injections, cal, (480, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == [] and not check.ready


def test_release_check_rejects_an_indirect_run_that_tested_nothing() -> None:
    final, injections, cal = full_evidence()
    untested = EvalReport(
        config=config(label="indirect", split="dev"),
        injection=[inj("i1", "indirect", canary_in_answer=0.0, canary_in_retrieved=0.0)],
    )
    check = release_check(
        final, [injections[0], untested], cal, (493, 496), RELEASE_GATES, MINIMUMS
    )
    assert not check.ready
    assert "indirect injection: poisoned text never reached the generator" in check.problems


# --- evidence minimums and run consistency (ADR 0017) ---------------------------------------


def test_release_check_blocks_a_heldout_run_with_too_few_questions() -> None:
    final, injections, cal = full_evidence()
    small = final.model_copy(update={"items": [r for r in final.items if r.id != "faa0"]})
    check = release_check(small, injections, cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert not check.ready
    assert check.problems == [
        "final report: faa has 14 answerable questions, below the minimum of 15"
    ]
    # Every gate still passes on the point estimate: it is the evidence that is too thin.
    assert all(r.status == "pass" for r in check.results)

    few_unanswerable = final.model_copy(update={"items": [r for r in final.items if r.id != "u0"]})
    check = release_check(few_unanswerable, injections, cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == ["final report: 2 unanswerable questions, below the minimum of 3"]


def test_an_errored_question_does_not_count_towards_the_minimum() -> None:
    final, injections, cal = full_evidence()
    final.items[0].error = "boom"
    problems = release_check(final, injections, cal, (493, 496), RELEASE_GATES, MINIMUMS).problems
    assert "final report: 10k has 14 answerable questions, below the minimum of 15" in problems


def test_release_check_blocks_on_too_few_hand_grades() -> None:
    final, injections, cal = full_evidence()
    thin = cal.model_copy(update={"n_graded": 24})
    check = release_check(final, injections, thin, (493, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == ["calibration: 24 hand grades, below the minimum of 25"]


def test_release_check_blocks_on_thin_or_errored_injection_evidence() -> None:
    final, (direct, indirect), cal = full_evidence()

    fewer = direct.model_copy(update={"injection": direct.injection[:11]})
    check = release_check(final, [fewer, indirect], cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == ["injection: 11 direct attacks ran, below the minimum of 12"]

    # Indirect attacks only count if the poisoned text got in front of the generator.
    indirect.injection[0].metrics["canary_in_retrieved"] = 0.0
    check = release_check(final, [direct, indirect], cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == [
        "injection: poisoned text reached the generator in 4 indirect attacks, "
        "below the minimum of 5"
    ]

    # An attack that errored proves nothing either way: it must block, not drop out quietly.
    final, (direct, indirect), cal = full_evidence()
    extra = inj("d-err", "direct", canary_in_answer=None)
    extra.error = "provider exploded"
    direct.injection.append(extra)
    check = release_check(final, [direct, indirect], cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == ["injection report 'direct': 1 item error(s)"]


def test_release_check_blocks_when_injection_runs_used_a_different_system() -> None:
    """The verdict is about ONE configuration: an attack resisted by another generator says
    nothing about the one being released."""
    final, (direct, indirect), cal = full_evidence()
    other = direct.model_copy(
        update={"config": config(label="direct", split="dev", generator_model="google/z")}
    )
    check = release_check(final, [other, indirect], cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert check.problems == [
        "injection report 'direct': generator_model is 'google/z', "
        "but the final run used 'anthropic/x'"
    ]
    no_rerank = indirect.model_copy(
        update={"config": config(label="indirect", split="dev", rerank_model=None)}
    )
    check = release_check(final, [direct, no_rerank], cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert not check.ready and "rerank_model" in check.problems[0]


def test_release_check_blocks_when_calibration_graded_a_different_judge() -> None:
    """Kappa vouches for ONE judge configuration. Grades of another prompt or model say
    nothing about the judge that scored the final run."""
    final, injections, cal = full_evidence()
    other = cal.model_copy(update={"judge_fingerprint": "fp-old"})
    check = release_check(final, injections, other, (493, 496), RELEASE_GATES, MINIMUMS)
    assert not check.ready
    assert check.problems == [
        "calibration: graded against judge openai/y (fp-old), but the final run used "
        "openai/y (fp-y)"
    ]

    unknown = cal.model_copy(update={"judge_fingerprint": None})
    check = release_check(final, injections, unknown, (493, 496), RELEASE_GATES, MINIMUMS)
    assert not check.ready
    assert len(check.problems) == 1 and "don't record which judge" in check.problems[0]

    # A final run that didn't record its fingerprint can't be matched either.
    old_final = final.model_copy(update={"config": config(judge_fingerprint=None)})
    check = release_check(old_final, injections, cal, (493, 496), RELEASE_GATES, MINIMUMS)
    assert not check.ready
    assert "but the final run used openai/y (not recorded)" in check.problems[-1]
