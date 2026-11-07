"""Metric functions: pure, so tested on small hand-made cases."""

import random
from decimal import Decimal

import pytest

from multimodal_doc_rag.evals.gold import GoldItem, GoldPage
from multimodal_doc_rag.evals.metrics import (
    citation_accuracy,
    distribution,
    extract_numbers,
    groupings,
    is_abstention,
    item_metrics,
    mean_ci,
    metric_table,
    numeric_match,
    percentile,
    recall_at_k,
    stratified_sample,
)
from multimodal_doc_rag.evals.results import ItemResult
from multimodal_doc_rag.fakes import IDK
from multimodal_doc_rag.types import PageRef, Passage


def passage(cid: int, doc: str = "d1", start: int = 0, end: int | None = None) -> Passage:
    return Passage(
        chunk_id=cid,
        doc_key=doc,
        doc_title=doc,
        kind="text",
        page_start=PageRef(start, f"{start + 1}"),
        page_end=PageRef(start if end is None else end, None),
        content="text",
        context_header="",
        score=1.0,
    )


def gp(doc: str, idx: int) -> GoldPage:
    return GoldPage(doc=doc, page_idx=idx)


# --- recall ---------------------------------------------------------------------------------


def test_recall_hits_within_k_by_page_idx_range() -> None:
    gold = [gp("d1", 5)]
    spans = passage(1, "d1", 4, 6)  # a chunk spanning pages 4..6 covers page 5
    assert recall_at_k(gold, [spans])
    assert not recall_at_k(gold, [passage(1, "d1", 6, 7)])  # just past the page
    assert not recall_at_k(gold, [passage(1, "other", 5)])  # right page, wrong document


def test_recall_respects_k_cutoff_and_any_gold_page() -> None:
    passages = [passage(i, "d1", i) for i in range(10)]
    assert not recall_at_k([gp("d1", 7)], passages, k=5)
    assert recall_at_k([gp("d1", 7)], passages, k=8)
    assert recall_at_k([gp("d1", 99), gp("d1", 2)], passages, k=5)  # any gold page counts
    assert not recall_at_k([gp("d1", 0)], [])
    with pytest.raises(ValueError):
        recall_at_k([gp("d1", 0)], passages, k=0)


# --- citation accuracy ----------------------------------------------------------------------


def test_citation_accuracy_share_of_citations_on_gold_pages() -> None:
    gold = [gp("d1", 3)]
    cited = [passage(1, "d1", 3), passage(2, "d1", 9), passage(3, "d2", 3)]
    assert citation_accuracy(gold, cited) == pytest.approx(1 / 3)
    assert citation_accuracy(gold, [passage(1, "d1", 3)]) == 1.0
    assert citation_accuracy(gold, []) is None  # nothing cited: undefined, not zero


# --- abstention -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, expected",
    [
        (IDK, True),
        ("  " + IDK.upper() + "  ", True),
        (IDK.replace(" ", "\n"), True),  # whitespace is normalised
        (IDK + " The documents cover other topics.", True),  # starts with it
        ("Well, " + IDK, False),  # only a *leading* IDK counts
        ("Apple sold 3 phones [1].", False),
        ("", False),
    ],
)
def test_is_abstention(answer: str, expected: bool) -> None:
    assert is_abstention(answer) is expected


# --- numbers --------------------------------------------------------------------------------


def values(text: str) -> list[Decimal]:
    return [m.value for m in extract_numbers(text)]


def test_extract_numbers_formats() -> None:
    assert values("Revenue was $391,035 million") == [Decimal(391_035_000_000)]
    assert values("up 12.5% and 3 percent") == [Decimal("12.5"), Decimal(3)]
    assert values("$1.2 billion and $5B and 7m") == [
        Decimal(1_200_000_000),
        Decimal(5_000_000_000),
        Decimal(7_000_000),
    ]
    assert values("a loss of (1,234) and $(56)") == [Decimal(-1234), Decimal(-56)]
    assert values("change of -4.5 points") == [Decimal("-4.5")]
    assert values("see page 4-9") == [Decimal(4), Decimal(9)]  # hyphen is not a minus
    assert values("no numbers here") == []
    assert values("2 thousand") == [Decimal(2000)]


def test_numeric_match_basic() -> None:
    assert numeric_match("Net sales were $391.0 billion.", "Net sales: $391.0 billion [1].")
    assert numeric_match("$391,035 million", "391035 million dollars")
    assert not numeric_match("$391 billion", "About $390 billion")
    assert numeric_match("no figures", "anything") is None  # not applicable


def test_numeric_match_requires_every_reference_number() -> None:
    ref = "Revenue rose from $100 million to $120 million."
    assert numeric_match(ref, "It was $100 million then $120 million.")
    assert not numeric_match(ref, "Revenue reached $120 million.")


def test_numeric_match_units_and_signs() -> None:
    assert numeric_match("$383 million", "383")  # table states units once
    assert numeric_match("383", "$383 million")
    assert numeric_match("(1,234)", "It fell by $1,234.")
    assert numeric_match("12%", "12 percent")
    assert not numeric_match("5 million", "5 billion")


def test_numeric_match_ignores_citation_markers() -> None:
    assert numeric_match("There are 2 engines.", "There are four engines [2].") is False
    assert numeric_match("There is 1 engine.", "There is 1 engine [1].")
    assert numeric_match("There is 1 engine.", "There is a single engine [1].") is False


# --- per-item -------------------------------------------------------------------------------


def gold_item(**kw: object) -> GoldItem:
    base: dict[str, object] = {
        "id": "x-1",
        "corpus": "10k",
        "split": "dev",
        "type": "fact",
        "question": "q",
        "answerable": True,
        "reference_answer": "$5 million",
        "gold_pages": [gp("d1", 2)],
    }
    return GoldItem.model_validate(base | kw)


def test_item_metrics_answerable() -> None:
    passages = [passage(1, "d1", 0), passage(2, "d1", 2)]
    m = item_metrics(gold_item(), "It is $5 million [2].", passages, [2])
    assert m["recall"] == 1.0
    assert m["citation_accuracy"] == 1.0
    assert m["numeric_match"] == 1.0
    assert m["false_abstention"] == 0.0
    assert m["abstention"] is None


def test_item_metrics_answerable_miss_and_false_abstention() -> None:
    m = item_metrics(gold_item(), IDK, [passage(1, "d1", 0)], [])
    assert m["recall"] == 0.0
    assert m["citation_accuracy"] is None
    assert m["numeric_match"] == 0.0
    assert m["false_abstention"] == 1.0


def test_item_metrics_unanswerable() -> None:
    item = gold_item(answerable=False, reference_answer=None, gold_pages=[])
    declined = item_metrics(item, IDK, [passage(1)], [])
    assert declined["abstention"] == 1.0
    assert declined["recall"] is None and declined["false_abstention"] is None
    assert item_metrics(item, "Sure: 42.", [passage(1)], [1])["abstention"] == 0.0


def test_item_metrics_uses_recall_k() -> None:
    passages = [passage(i, "d1", i + 10) for i in range(5)] + [passage(9, "d1", 2)]
    assert item_metrics(gold_item(), "a", passages, [], recall_k=5)["recall"] == 0.0
    assert item_metrics(gold_item(), "a", passages, [], recall_k=6)["recall"] == 1.0


# --- aggregation ----------------------------------------------------------------------------


def test_mean_ci_is_deterministic_and_brackets_the_mean() -> None:
    vals = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    a, b = mean_ci(vals), mean_ci(vals)
    assert a == b
    assert a.mean == pytest.approx(0.7)
    assert a.lo is not None and a.hi is not None and a.mean is not None
    assert a.lo <= a.mean <= a.hi
    assert a.n == 10


def test_mean_ci_edge_cases() -> None:
    assert mean_ci([]) == mean_ci([])
    assert mean_ci([]).mean is None and mean_ci([]).n == 0
    one = mean_ci([0.5])
    assert (one.mean, one.lo, one.hi) == (0.5, 0.5, 0.5)
    same = mean_ci([1.0, 1.0, 1.0])
    assert (same.lo, same.hi) == (1.0, 1.0)


def test_percentile_and_distribution() -> None:
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(vals, 50) == 30.0
    assert percentile(vals, 0) == 10.0 and percentile(vals, 100) == 50.0
    assert percentile(vals, 95) == pytest.approx(48.0)
    assert percentile([7.0], 95) == 7.0
    d = distribution(vals)
    assert (d.n, d.mean, d.p50) == (5, 30.0, 30.0)
    assert distribution([]).mean is None
    with pytest.raises(ValueError):
        percentile([], 50)


def result(id: str, corpus: str, split: str, type_: str, **metrics: float | None) -> ItemResult:
    return ItemResult(
        id=id,
        corpus=corpus,
        split=split,
        type=type_,
        question="q",
        answerable=True,
        reference_answer="a",
        gold_pages=[],
        metrics=metrics,
    )


def test_groupings_and_metric_table() -> None:
    rs = [
        result("1", "faa", "dev", "fact", recall=1.0),
        result("2", "faa", "dev", "figure", recall=0.0),
        result("3", "10k", "heldout", "fact", recall=None),
    ]
    names = [n for n, _ in groupings(rs)]
    assert names[0] == "overall"
    assert "faa / dev" in names and "faa / dev / figure" in names and "10k / heldout" in names
    overall = dict(groupings(rs))["overall"]
    table = metric_table(overall, ["recall", "correctness"])
    assert table["recall"].mean == 0.5 and table["recall"].n == 2  # None is skipped
    assert table["correctness"].n == 0  # no judge ran


def test_errored_items_are_excluded_from_metric_tables() -> None:
    bad = result("e", "faa", "dev", "fact", recall=0.0)
    bad.error = "boom"
    assert metric_table([bad], ["recall"])["recall"].n == 0


def test_stratified_sample_round_robin_and_reproducible() -> None:
    strata = {"a": list(range(10)), "b": list(range(100, 102)), "c": [200]}
    first = stratified_sample(strata, 6, random.Random(3))
    assert first == stratified_sample(strata, 6, random.Random(3))
    assert len(first) == 6
    assert any(x >= 200 for x in first) and any(100 <= x < 200 for x in first)
    assert sorted(stratified_sample(strata, 99, random.Random(0))) == sorted(
        [*range(10), 100, 101, 200]
    )
