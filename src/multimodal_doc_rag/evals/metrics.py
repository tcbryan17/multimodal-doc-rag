"""Pure scoring functions (ADR 0011). No I/O, no models: everything here is unit-tested.

Pages are always compared by `idx` (0-based position in the source file), never by printed
label: labels like "4-9" and "4-12" don't order numerically and some pages have none.
"""

import random
import re
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from multimodal_doc_rag.evals.gold import GoldItem, GoldPage
from multimodal_doc_rag.evals.results import ItemResult
from multimodal_doc_rag.fakes import IDK
from multimodal_doc_rag.types import Passage

# --- retrieval ------------------------------------------------------------------------------


def passage_covers(passage: Passage, page: GoldPage) -> bool:
    """True if the passage is from the gold page's document and its page range includes the
    gold page. A chunk may span a page break (ADR 0007), hence a range, not a single page."""
    return passage.doc_key == page.doc and passage.page_start.idx <= page.page_idx <= (
        passage.page_end.idx
    )


def recall_at_k(gold_pages: Sequence[GoldPage], passages: Sequence[Passage], k: int = 5) -> bool:
    """Hit if ANY of the first k retrieved passages covers ANY gold page.

    "Any" on both sides because a question can legitimately be answered from several pages
    (or one chunk can span two). Meaningful for answerable items only; with no gold pages
    nothing can be hit, so it returns False and callers skip unanswerable items.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    return any(passage_covers(p, g) for p in passages[:k] for g in gold_pages)


def citation_accuracy(
    gold_pages: Sequence[GoldPage], cited_passages: Sequence[Passage]
) -> float | None:
    """Share of the answer's citations that point at a gold page.

    A citation is one cited passage (the answer's `[n]` markers, validated to passages that
    were actually retrieved). It is correct when that passage covers at least one gold page.
    Returns None when the answer cites nothing (the ratio is undefined; "answered without
    citing" is visible separately as a missing value, not as a zero).
    """
    if not cited_passages:
        return None
    ok = sum(1 for p in cited_passages if any(passage_covers(p, g) for g in gold_pages))
    return ok / len(cited_passages)


# --- abstention -----------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def is_abstention(answer: str) -> bool:
    """True if the answer is the fixed "I don't know" reply: equal to it after normalising
    whitespace and case, or STARTING with it (a model may add a sentence after)."""
    a = _norm(answer)
    idk = _norm(IDK)
    return a == idk or a.startswith(idk)


# --- numbers --------------------------------------------------------------------------------

_SCALES = {
    "thousand": Decimal(1_000),
    "million": Decimal(1_000_000),
    "billion": Decimal(1_000_000_000),
    "trillion": Decimal(1_000_000_000_000),
    "bn": Decimal(1_000_000_000),
    "m": Decimal(1_000_000),
    "b": Decimal(1_000_000_000),
}

_NUMBER = re.compile(
    r"""
    (?P<open>\$?\(\s*)?                      # "(1,234)" or "$(1,234)": accounting negative
    (?:(?<![\w.])(?P<neg>[-−]))?        # a minus, but not the hyphen in "4-9"
    \$?\s?
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
    (?:\s*(?P<word>%|percent\b|thousand\b|million\b|billion\b|trillion\b)
       |(?P<abbr>bn|[mb])\b)?                # "$5B", "5m" must be attached to the digits
    (?P<close>\s*\))?
    """,
    re.VERBOSE | re.IGNORECASE,
)
_CITATION_MARKER = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")


@dataclass(frozen=True)
class NumberMention:
    value: Decimal  # signed, with any scale word applied ("1.2 billion" -> 1200000000)
    raw: Decimal  # as written ("1.2")
    scaled: bool  # a scale word/abbreviation was present


def extract_numbers(text: str) -> list[NumberMention]:
    """Every number in the text, understanding $, thousands commas, %, "percent",
    thousand/million/billion/trillion (and $5B / 5m), minus signs and (1,234) negatives."""
    out: list[NumberMention] = []
    for m in _NUMBER.finditer(text):
        try:
            raw = Decimal(m.group("num").replace(",", ""))
        except InvalidOperation:  # pragma: no cover - the regex only admits valid numbers
            continue
        scale_key = (m.group("word") or m.group("abbr") or "").lower()
        factor = _SCALES.get(scale_key)
        value = raw * factor if factor is not None else raw
        accounting_negative = bool(m.group("open")) and bool(m.group("close"))
        if m.group("neg") or accounting_negative:
            value, raw = -value, -raw
        out.append(NumberMention(value=value, raw=raw, scaled=factor is not None))
    return out


def _same_number(ref: NumberMention, ans: NumberMention) -> bool:
    # Sign-insensitive: prose says "fell by $1,234" where the table says (1,234).
    if abs(ref.value) == abs(ans.value):
        return True
    # Tables state units once ("in millions"), so "$383 million" in a reference and "383" in
    # an answer (or the reverse) is the same figure: allow a raw match when exactly one side
    # carries a scale word.
    return ref.scaled != ans.scaled and abs(ref.raw) == abs(ans.raw)


def numeric_match(reference: str, answer: str) -> bool | None:
    """Exact match on numbers: True if EVERY number in the reference appears in the answer.

    None when the reference contains no numbers (the metric doesn't apply). Citation
    markers like "[2]" are removed from the answer first, so "[1]" can't satisfy a "1".
    """
    ref_numbers = extract_numbers(reference)
    if not ref_numbers:
        return None
    ans_numbers = extract_numbers(_CITATION_MARKER.sub(" ", answer))
    return all(any(_same_number(r, a) for a in ans_numbers) for r in ref_numbers)


# --- per-item scoring -----------------------------------------------------------------------


def item_metrics(
    item: GoldItem,
    answer: str,
    passages: Sequence[Passage],
    cited_chunk_ids: Iterable[int],
    recall_k: int = 5,
) -> dict[str, float | None]:
    """The rule-based metrics for one answered question; None = not defined for this item."""
    cited_ids = set(cited_chunk_ids)
    cited = [p for p in passages if p.chunk_id in cited_ids]
    abstained = is_abstention(answer)
    metrics: dict[str, float | None] = {
        "recall": None,
        "citation_accuracy": None,
        "numeric_match": None,
        "abstention": None,  # unanswerable items: did it decline?
        "false_abstention": None,  # answerable items: did it decline anyway?
    }
    if item.answerable:
        metrics["recall"] = float(recall_at_k(item.gold_pages, passages, recall_k))
        metrics["citation_accuracy"] = citation_accuracy(item.gold_pages, cited)
        match = numeric_match(item.reference_answer or "", answer)
        metrics["numeric_match"] = None if match is None else float(match)
        metrics["false_abstention"] = float(abstained)
    else:
        metrics["abstention"] = float(abstained)
    return metrics


# --- aggregation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class MeanCI:
    mean: float | None  # None when there were no values
    lo: float | None
    hi: float | None
    n: int


def mean_ci(
    values: Sequence[float], *, resamples: int = 2000, seed: int = 0, level: float = 0.95
) -> MeanCI:
    """Mean with a percentile-bootstrap confidence interval.

    Resample the values with replacement `resamples` times, take each resample's mean, and
    read the CI off the middle `level` of those means. With ~60 questions per set the CI is
    wide, which is the honest picture: differences smaller than it are noise. Seeded, so the
    same data always gives the same interval.
    """
    n = len(values)
    if n == 0:
        return MeanCI(None, None, None, 0)
    mean = statistics.fmean(values)
    if n == 1 or len(set(values)) == 1:
        return MeanCI(mean, mean, mean, n)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(resamples))
    tail = (1 - level) / 2
    lo = means[int(tail * resamples)]
    hi = means[min(resamples - 1, int((1 - tail) * resamples))]
    return MeanCI(mean, lo, hi, n)


def percentile(values: Sequence[float], q: float) -> float:
    """q in [0, 100], linear interpolation between closest ranks."""
    if not values:
        raise ValueError("percentile of no values")
    s = sorted(values)
    pos = (len(s) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


@dataclass(frozen=True)
class Distribution:
    n: int
    mean: float | None
    p50: float | None
    p95: float | None


def distribution(values: Sequence[float]) -> Distribution:
    if not values:
        return Distribution(0, None, None, None)
    return Distribution(
        len(values), statistics.fmean(values), percentile(values, 50), percentile(values, 95)
    )


RULE_METRICS = (
    "recall",
    "citation_accuracy",
    "numeric_match",
    "abstention",
    "false_abstention",
)
JUDGE_METRICS = ("correctness", "faithfulness")


def result_metrics(r: ItemResult) -> dict[str, float | None]:
    """The item's rule metrics plus the judge's scores (when it was judged)."""
    m = dict(r.metrics)
    if r.verdict is not None:
        m["correctness"] = r.verdict.correctness
        m["faithfulness"] = float(r.verdict.faithfulness)
    return m


def metric_table(
    results: Sequence[ItemResult], names: Sequence[str] = RULE_METRICS + JUDGE_METRICS
) -> dict[str, MeanCI]:
    """Mean + CI per metric over the items where that metric is defined."""
    per_item = [result_metrics(r) for r in results if r.error is None]
    return {
        name: mean_ci([v for m in per_item if (v := m.get(name)) is not None]) for name in names
    }


def groupings(results: Sequence[ItemResult]) -> list[tuple[str, list[ItemResult]]]:
    """overall, then per corpus, per corpus × split, per corpus × split × type (non-empty)."""
    keyers: list[Callable[[ItemResult], str]] = [
        lambda r: "overall",
        lambda r: r.corpus,
        lambda r: f"{r.corpus} / {r.split}",
        lambda r: f"{r.corpus} / {r.split} / {r.type}",
    ]
    out: list[tuple[str, list[ItemResult]]] = []
    for keyer in keyers:
        groups: dict[str, list[ItemResult]] = {}
        for r in results:
            groups.setdefault(keyer(r), []).append(r)
        out.extend(sorted(groups.items()))
    return out


# --- agreement helpers shared with calibration ----------------------------------------------


def stratified_sample[T](strata: dict[str, list[T]], n: int, rng: random.Random) -> list[T]:
    """Pick up to n items round-robin across strata (so every group is represented before any
    group gets a second item). Each stratum is shuffled with the seeded rng; strata are
    visited in sorted-key order, so the result is reproducible."""
    pools = {k: rng.sample(v, len(v)) for k, v in sorted(strata.items())}
    picked: list[T] = []
    while len(picked) < n and any(pools.values()):
        for key in pools:
            if pools[key] and len(picked) < n:
                picked.append(pools[key].pop())
    return picked
