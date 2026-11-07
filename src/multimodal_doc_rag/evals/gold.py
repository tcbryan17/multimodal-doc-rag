"""Gold-set schema and JSONL storage (ADR 0011).

A gold item is one question with the pages that answer it. The owner verifies every item
(a model only drafts), so each carries a `status` and an `origin`.

Storage is deterministic on purpose: sorted by id, one JSON object per line, fields in
declaration order. A re-save of unchanged data produces a byte-identical file, so git diffs
show only real edits.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CorpusName = Literal["10k", "faa"]
SplitName = Literal["dev", "heldout"]
QuestionType = Literal["fact", "figure", "concept"]
Status = Literal["draft", "verified", "rejected"]
Origin = Literal["llm_draft", "owner"]


class GoldError(ValueError):
    """A gold file is malformed or inconsistent."""


class GoldPage(BaseModel):
    """A page that answers the question. `page_idx` is what scoring compares; `page_label`
    (the printed number, e.g. "8-22") is only for the human reviewing the item."""

    model_config = ConfigDict(extra="forbid")

    doc: str  # doc_key, e.g. "phak-ch08"
    page_idx: int = Field(ge=0)
    page_label: str | None = None


class GoldItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str  # e.g. "faa-dev-001"
    corpus: CorpusName
    split: SplitName
    type: QuestionType
    question: str = Field(min_length=1)
    answerable: bool
    reference_answer: str | None = None
    gold_pages: list[GoldPage] = Field(default_factory=list)
    status: Status = "draft"
    origin: Origin = "llm_draft"
    notes: str = ""
    # Provenance for drafted items: the chunk text the question was written from, so the
    # reviewer (and a future reader of the file) can check the item without the database.
    source_excerpt: str = ""

    @model_validator(mode="after")
    def _answerability(self) -> Self:
        if self.answerable:
            if not (self.reference_answer and self.reference_answer.strip()):
                raise ValueError("an answerable item needs a reference_answer")
            if not self.gold_pages:
                raise ValueError("an answerable item needs at least one gold page")
        elif self.gold_pages:
            # An unanswerable question has no right page: recall is undefined for it, and a
            # page listed here would be scored as if it were.
            raise ValueError("an unanswerable item must not have gold pages")
        return self


class InjectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["direct", "indirect"]
    question: str = Field(min_length=1)
    attack_goal: str  # plain language: what attacker success looks like
    # A string that appears in the answer only if the attack worked. Direct questions build
    # it from pieces ("join ZEB and RA-7741") so merely repeating the question can't show it.
    canary: str | None = None
    status: Status = "draft"


class _HasId(Protocol):
    @property
    def id(self) -> str: ...


# --- JSONL ----------------------------------------------------------------------------------


def _dump_lines(items: Iterable[BaseModel]) -> str:
    return "".join(json.dumps(i.model_dump(mode="json"), ensure_ascii=False) + "\n" for i in items)


def _check_unique(path: Path, items: Sequence[_HasId]) -> None:
    ids = [i.id for i in items]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise GoldError(f"{path}: duplicate ids {dupes}")


def load_gold(path: Path) -> list[GoldItem]:
    if not path.exists():
        return []
    items: list[GoldItem] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(GoldItem.model_validate_json(line))
        except ValidationError as exc:
            raise GoldError(f"{path}:{n}: {exc}") from exc
    _check_unique(path, items)
    return items


def save_gold(path: Path, items: Sequence[GoldItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered: list[GoldItem] = sorted(items, key=lambda i: i.id)
    path.write_text(_dump_lines(ordered), encoding="utf-8")


def load_injection(path: Path) -> list[InjectionItem]:
    if not path.exists():
        return []
    items: list[InjectionItem] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(InjectionItem.model_validate_json(line))
        except ValidationError as exc:
            raise GoldError(f"{path}:{n}: {exc}") from exc
    _check_unique(path, items)
    return items


def save_injection(path: Path, items: Sequence[InjectionItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered: list[InjectionItem] = sorted(items, key=lambda i: i.id)
    path.write_text(_dump_lines(ordered), encoding="utf-8")


# --- consistency with the corpus manifest -------------------------------------------------------


def split_problems(item: GoldItem, doc_splits: Mapping[str, str]) -> list[str]:
    """Why this item's split disagrees with its documents' manifest split (empty = fine).

    ADR 0011/0013: held-out questions may only point at held-out documents and dev questions
    only at dev documents. Otherwise a "held-out" number could be tuned against, or a dev
    number would quietly include held-out material.
    """
    problems: list[str] = []
    for page in item.gold_pages:
        doc_split = doc_splits.get(page.doc)
        if doc_split is None:
            problems.append(f"{item.id}: doc {page.doc!r} is not in the manifest")
        elif doc_split != item.split:
            problems.append(
                f"{item.id}: split is {item.split!r} but {page.doc!r} is "
                f"{doc_split!r} in the manifest"
            )
    return problems


def check_splits(items: Iterable[GoldItem], doc_splits: Mapping[str, str]) -> None:
    """Raise GoldError listing every mismatch. Called by the runner and the drafter."""
    problems = [p for item in items for p in split_problems(item, doc_splits)]
    if problems:
        raise GoldError("gold items disagree with the corpus manifest:\n  " + "\n  ".join(problems))


def verified(items: Iterable[GoldItem]) -> list[GoldItem]:
    """Runs only include owner-verified items; drafts and rejects never count."""
    return [i for i in items if i.status == "verified"]
