"""Reviewing drafted gold items: pure state transitions plus a thin interactive loop.

The loop takes `ask` (read a line) and `say` (print a line) as parameters, so tests drive it
with scripted answers and the real CLI passes `input` and `print`. All the decisions about
what a keypress DOES live in the pure functions above it.
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from multimodal_doc_rag.evals.gold import (
    CorpusName,
    GoldItem,
    GoldPage,
    InjectionItem,
    QuestionType,
    SplitName,
    Status,
    split_problems,
)

# --- pure transitions -----------------------------------------------------------------------


def pending(items: Sequence[GoldItem]) -> list[GoldItem]:
    """Drafts still waiting for the owner, in id order."""
    return sorted((i for i in items if i.status == "draft"), key=lambda i: i.id)


def with_changes(item: GoldItem, **changes: Any) -> GoldItem:
    """A copy with fields changed, re-validated (model_copy would skip validation, and an
    invalid item must never be saved). Raises pydantic.ValidationError."""
    return GoldItem.model_validate({**item.model_dump(), **changes})


def verify(item: GoldItem, doc_splits: Mapping[str, str] | None = None) -> GoldItem:
    """Mark verified, after checking its pages belong to the item's split (when the manifest
    is known). Raises ValueError with the reasons otherwise."""
    if doc_splits is not None:
        problems = split_problems(item, doc_splits)
        if problems:
            raise ValueError("; ".join(problems))
    return with_changes(item, status="verified")


def reject(item: GoldItem) -> GoldItem:
    return with_changes(item, status="rejected")


def replace_item(items: Sequence[GoldItem], new: GoldItem) -> list[GoldItem]:
    return [new if i.id == new.id else i for i in items]


def parse_pages(text: str) -> list[GoldPage]:
    """'phak-ch08:12:8-3, phak-ch08:13' -> pages (doc:page_idx[:printed_label], comma-separated)."""
    pages: list[GoldPage] = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        bits = part.split(":")
        if len(bits) not in (2, 3) or not bits[1].strip().isdigit():
            raise ValueError(f"bad page {part!r}: write doc:page_idx or doc:page_idx:label")
        label = bits[2].strip() if len(bits) == 3 and bits[2].strip() else None
        pages.append(GoldPage(doc=bits[0].strip(), page_idx=int(bits[1]), page_label=label))
    return pages


def format_pages(pages: Sequence[GoldPage]) -> str:
    return ", ".join(
        f"{p.doc}:{p.page_idx}" + (f":{p.page_label}" if p.page_label else "") for p in pages
    )


def owner_item(
    *,
    id: str,
    corpus: CorpusName,
    split: SplitName,
    type: QuestionType,
    question: str,
    reference_answer: str | None,
    pages: str,
    notes: str = "",
) -> GoldItem:
    """An item the owner wrote by hand (the figure questions). Already verified: the author
    is the verifier. No pages and no reference means an unanswerable question."""
    answerable = bool(reference_answer)
    return GoldItem(
        id=id,
        corpus=corpus,
        split=split,
        type=type,
        question=question,
        answerable=answerable,
        reference_answer=reference_answer or None,
        gold_pages=parse_pages(pages) if answerable else [],
        status="verified",
        origin="owner",
        notes=notes,
    )


# --- interactive loop -----------------------------------------------------------------------

Ask = Callable[[str], str]
Say = Callable[[str], None]
Save = Callable[[Sequence[GoldItem]], None]

MENU = "[v]erify  [e]dit  [r]eject  [s]kip  [q]uit > "


def show(item: GoldItem, say: Say, position: str = "") -> None:
    pages = ", ".join(f"{p.doc} p.{p.page_label or p.page_idx + 1}" for p in item.gold_pages)
    say("")
    kind = "answerable" if item.answerable else "UNANSWERABLE"
    say(f"=== {item.id} {position} ({item.type}, {kind})")
    say(f"Question:  {item.question}")
    say(f"Reference: {item.reference_answer or '(none: documents should not answer this)'}")
    say(f"Pages:     {pages or '(none)'}")
    if item.notes:
        say(f"Notes:     {item.notes}")
    say("--- source text the draft was written from ---")
    say(item.source_excerpt or "(not recorded)")
    say("---")


def edit_item(item: GoldItem, ask: Ask, say: Say) -> GoldItem:
    """Prompt per field; a blank answer keeps the current value. Returns the original item
    if the edited result is invalid."""
    changes: dict[str, Any] = {}
    q = ask(f"question [{item.question}]\n> ").strip()
    if q:
        changes["question"] = q
    ans = ask(f"answerable y/n [{'y' if item.answerable else 'n'}] > ").strip().lower()
    answerable = item.answerable if ans not in ("y", "n") else ans == "y"
    changes["answerable"] = answerable
    if answerable:
        ref = ask(f"reference answer [{item.reference_answer or ''}]\n> ").strip()
        if ref:
            changes["reference_answer"] = ref
        pages = ask(
            f"gold pages doc:idx[:label], ... [{format_pages(item.gold_pages)}]\n> "
        ).strip()
        if pages:
            try:
                changes["gold_pages"] = parse_pages(pages)
            except ValueError as exc:
                say(f"  {exc}; keeping the old pages")
    else:
        changes["reference_answer"] = None
        changes["gold_pages"] = []
    qtype = ask(f"type fact/figure/concept [{item.type}] > ").strip().lower()
    if qtype:
        changes["type"] = qtype
    notes = ask(f"notes [{item.notes}] > ").strip()
    if notes:
        changes["notes"] = notes
    try:
        return with_changes(item, **changes)
    except ValidationError as exc:
        say(f"  not saved, the edit is invalid: {exc.errors()[0]['msg']}")
        return item


def review_loop(
    items: Sequence[GoldItem],
    ask: Ask,
    say: Say,
    save: Save,
    doc_splits: Mapping[str, str] | None = None,
) -> Counter[str]:
    """Walk the drafts one by one. Saves after EVERY decision, so quitting loses nothing."""
    current = list(items)
    counts: Counter[str] = Counter()
    todo = pending(current)
    for n, draft in enumerate(todo, start=1):
        item = draft
        while True:
            show(item, say, f"[{n}/{len(todo)}]")
            choice = ask(MENU).strip().lower()[:1]
            if choice == "v":
                try:
                    item = verify(item, doc_splits)
                except ValueError as exc:
                    say(f"  cannot verify: {exc}")
                    continue
                counts["verified"] += 1
            elif choice == "r":
                item = reject(item)
                counts["rejected"] += 1
            elif choice == "e":
                item = edit_item(item, ask, say)
                current = replace_item(current, item)  # keep edits even if skipped later
                save(current)
                continue
            elif choice == "s":
                counts["skipped"] += 1
            elif choice == "q":
                return counts
            else:
                say("  please answer v, e, r, s or q")
                continue
            current = replace_item(current, item)
            save(current)
            break
    return counts


def review_injection(
    items: Sequence[InjectionItem],
    ask: Ask,
    say: Say,
    save: Callable[[Sequence[InjectionItem]], None],
) -> Counter[str]:
    """Same idea for injection items: read each attack, then verify or reject."""
    current = list(items)
    counts: Counter[str] = Counter()
    todo = sorted((i for i in current if i.status == "draft"), key=lambda i: i.id)
    for n, item in enumerate(todo, start=1):
        say("")
        say(f"=== {item.id} [{n}/{len(todo)}] ({item.kind})")
        say(f"Question: {item.question}")
        say(f"Attack succeeds if: {item.attack_goal}")
        say(f"Canary: {item.canary or '(none: the judge decides)'}")
        while True:
            choice = ask("[v]erify  [r]eject  [s]kip  [q]uit > ").strip().lower()[:1]
            if choice in ("v", "r"):
                status: Status = "verified" if choice == "v" else "rejected"
                new = item.model_copy(update={"status": status})
                current = [new if i.id == new.id else i for i in current]
                counts["verified" if choice == "v" else "rejected"] += 1
                save(current)
                break
            if choice == "s":
                counts["skipped"] += 1
                break
            if choice == "q":
                return counts
            say("  please answer v, r, s or q")
    return counts
