"""Gold-set schema, JSONL round-trips and manifest/split consistency."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from multimodal_doc_rag.evals.gold import (
    GoldError,
    GoldItem,
    GoldPage,
    InjectionItem,
    check_splits,
    load_gold,
    load_injection,
    save_gold,
    save_injection,
    split_problems,
    verified,
)


def item(id: str = "faa-dev-001", **kw: object) -> GoldItem:
    base: dict[str, object] = {
        "id": id,
        "corpus": "faa",
        "split": "dev",
        "type": "fact",
        "question": "What does the altimeter measure?",
        "answerable": True,
        "reference_answer": "Altitude above a pressure level.",
        "gold_pages": [GoldPage(doc="phak-ch08", page_idx=3, page_label="8-4")],
    }
    return GoldItem.model_validate(base | kw)


def test_answerable_needs_reference_and_gold_page() -> None:
    with pytest.raises(ValidationError, match="reference_answer"):
        item(reference_answer=None)
    with pytest.raises(ValidationError, match="reference_answer"):
        item(reference_answer="   ")
    with pytest.raises(ValidationError, match="gold page"):
        item(gold_pages=[])


def test_unanswerable_must_not_have_gold_pages() -> None:
    ok = item(answerable=False, reference_answer=None, gold_pages=[])
    assert not ok.answerable
    with pytest.raises(ValidationError, match="must not have gold pages"):
        item(answerable=False)


def test_extra_fields_and_bad_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        item(surprise=1)
    with pytest.raises(ValidationError):
        item(split="test")
    with pytest.raises(ValidationError):
        GoldPage(doc="x", page_idx=-1)


def test_save_is_sorted_stable_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "faa.jsonl"
    items = [item("faa-dev-002"), item("faa-dev-001", question="Another?")]
    save_gold(path, items)
    first = path.read_text()
    assert [line.split('"')[3] for line in first.splitlines()] == ["faa-dev-001", "faa-dev-002"]
    loaded = load_gold(path)
    assert loaded == sorted(items, key=lambda i: i.id)
    save_gold(path, loaded)
    assert path.read_text() == first  # byte-identical re-save


def test_load_missing_file_is_empty_and_duplicates_are_errors(tmp_path: Path) -> None:
    assert load_gold(tmp_path / "nope.jsonl") == []
    path = tmp_path / "dup.jsonl"
    line = item().model_dump_json()
    path.write_text(f"{line}\n\n{line}\n")
    with pytest.raises(GoldError, match="duplicate ids"):
        load_gold(path)


def test_bad_line_reports_file_and_line_number(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(item().model_dump_json() + '\n{"id": "x"}\n')
    with pytest.raises(GoldError, match=r"bad.jsonl:2"):
        load_gold(path)


def test_split_must_match_manifest() -> None:
    splits = {"phak-ch08": "dev", "phak-ch11": "heldout"}
    assert split_problems(item(), splits) == []
    held = item("faa-held-001", split="heldout")
    problems = split_problems(held, splits)
    assert len(problems) == 1 and "heldout" in problems[0] and "phak-ch08" in problems[0]
    unknown = item(gold_pages=[GoldPage(doc="ghost", page_idx=0)])
    assert "not in the manifest" in split_problems(unknown, splits)[0]
    with pytest.raises(GoldError, match="disagree"):
        check_splits([item(), held], splits)
    check_splits([item()], splits)  # no error


def test_only_verified_items_are_selected() -> None:
    items = [item("a", status="verified"), item("b"), item("c", status="rejected")]
    assert [i.id for i in verified(items)] == ["a"]


def test_injection_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "direct.jsonl"
    items = [
        InjectionItem(id="d-2", kind="direct", question="q2", attack_goal="g", canary=None),
        InjectionItem(id="d-1", kind="direct", question="q1", attack_goal="g", canary="ZEBRA-1"),
    ]
    save_injection(path, items)
    loaded = load_injection(path)
    assert [i.id for i in loaded] == ["d-1", "d-2"]
    assert loaded[0].status == "draft"
    assert load_injection(tmp_path / "missing.jsonl") == []
