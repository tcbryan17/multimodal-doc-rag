"""Keep docs/concepts/ honest: every code reference must point at something that exists.

A study guide that names `search.py::rrf` is only useful while `rrf` is still there. This test
reads each guide, finds every backticked `src/....py::symbol` reference, and checks with `ast`
that the file exists and the symbol is defined. It also checks that each numbered guide has
the six required sections.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONCEPTS = ROOT / "docs" / "concepts"

# `src/multimodal_doc_rag/search.py::rrf` or `...pipeline.py::RagPipeline._rerank`
REF = re.compile(r"`(src/[\w/]+\.py)::([\w.]+)`")
SECTIONS = (
    "## What it does",
    "## Where it lives",
    "## What was chosen and why",
    "## Options rejected",
    "## Evidence",
    "## Interview questions",
)


@dataclass(frozen=True)
class Ref:
    guide: str
    path: str
    symbol: str

    def __str__(self) -> str:
        return f"{self.guide}:{self.path}::{self.symbol}"


def guides() -> list[Path]:
    """The numbered guides (01-...md). README.md is the index, not a guide."""
    return sorted(p for p in CONCEPTS.glob("*.md") if p.name[:2].isdigit())


def find_refs() -> list[Ref]:
    found: dict[Ref, None] = {}  # ordered, de-duplicated
    for md in sorted(CONCEPTS.glob("*.md")):
        for path, symbol in REF.findall(md.read_text(encoding="utf-8")):
            found.setdefault(Ref(md.name, path, symbol), None)
    return list(found)


def top_level_names(tree: ast.Module) -> set[str]:
    """Functions, classes and module-level assignments (plain, annotated or `type X = ...`)."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.TypeAlias):
            names.add(node.name.id)
    return names


def class_members(tree: ast.Module, class_name: str) -> set[str] | None:
    """Methods and class attributes of a top-level class, or None if there is no such class."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            members: set[str] = set()
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    members.add(item.name)
                elif isinstance(item, ast.Assign):
                    members.update(t.id for t in item.targets if isinstance(t, ast.Name))
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    members.add(item.target.id)
            return members
    return None


def check_ref(ref: Ref) -> str | None:
    """None if the reference is valid, else a message saying what is wrong."""
    file = ROOT / ref.path
    if not file.is_file():
        return f"file {ref.path} does not exist"
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=ref.path)
    head, _, rest = ref.symbol.partition(".")
    if not rest:
        if head not in top_level_names(tree):
            return f"{ref.path} defines no top-level {head!r}"
        return None
    members = class_members(tree, head)
    if members is None:
        return f"{ref.path} defines no class {head!r}"
    if rest not in members:
        return f"class {head} in {ref.path} has no member {rest!r}"
    return None


REFS = find_refs()
GUIDES = guides()


def test_there_are_thirteen_guides_and_a_readme() -> None:
    assert (CONCEPTS / "README.md").is_file()
    assert [g.name[:2] for g in GUIDES] == [f"{n:02d}" for n in range(1, 14)]


def test_guides_contain_code_references() -> None:
    assert len(REFS) > 50  # guards against the regex silently matching nothing


@pytest.mark.parametrize("ref", REFS, ids=str)
def test_code_reference_exists(ref: Ref) -> None:
    problem = check_ref(ref)
    assert problem is None, f"{ref.guide}: {problem}"


@pytest.mark.parametrize("guide", GUIDES, ids=lambda g: g.name)
def test_guide_has_the_six_sections_in_order(guide: Path) -> None:
    text = guide.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == list(SECTIONS)


@pytest.mark.parametrize("guide", GUIDES, ids=lambda g: g.name)
def test_interview_questions_are_left_for_the_owner(guide: Path) -> None:
    """Each question is followed by a blank `**Your answer:**` line, and nothing is written
    after the last one: the owner writes the answers."""
    text = guide.read_text(encoding="utf-8")
    questions = text.split("## Interview questions", 1)[1]
    numbered = re.findall(r"^\d+\. ", questions, flags=re.MULTILINE)
    assert 4 <= len(numbered) <= 5
    assert questions.count("**Your answer:**") == len(numbered)
    assert questions.rstrip().endswith("**Your answer:**")
    for block in re.split(r"^\d+\. ", questions, flags=re.MULTILINE)[1:]:
        assert re.search(r"\n\n\*\*Your answer:\*\*\s*$", block), block
