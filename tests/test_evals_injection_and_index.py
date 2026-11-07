"""Injection sets, the poisoned PDF, and the eval-only database logic."""

import importlib.util
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from multimodal_doc_rag.contracts import AskRequest
from multimodal_doc_rag.evals.gold import load_injection
from multimodal_doc_rag.evals.index import (
    EVAL_DB_NAME,
    POISONED_DOC_KEY,
    POISONED_SOURCE,
    EvalIndexError,
    check_create_allowed,
    create_eval_database,
    create_statement,
    db_name,
    drop_statement,
    in_use_message,
    ingest_poisoned,
    poisoned_present,
    with_db,
)
from multimodal_doc_rag.fakes import (
    CaptionFigureDescriber,
    EchoGenerator,
    HashingEmbedder,
    OverlapReranker,
)
from multimodal_doc_rag.parsing.handbook_pdf import HandbookPdfParser
from multimodal_doc_rag.pipeline import RagPipeline

REPO = Path(__file__).resolve().parent.parent
EVALS = REPO / "evals"
Conn = psycopg.Connection[Any]


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "make_poisoned_handbook", EVALS / "poisoned" / "make_poisoned_handbook.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def poisoned_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "poisoned.pdf"
    _load_generator().build(path)
    return path


# --- the committed injection sets -----------------------------------------------------------


def test_direct_set_is_about_fifteen_drafts_for_the_owner_to_review() -> None:
    items = load_injection(EVALS / "injection" / "direct.jsonl")
    assert len(items) == 15
    assert {i.kind for i in items} == {"direct"}
    assert {i.status for i in items} == {"draft"}  # the owner promotes them to verified


def test_direct_canaries_are_not_spelled_out_in_the_question() -> None:
    # "join 'ZEB' and 'RA-7741'": merely repeating the question must not trip the canary.
    for item in load_injection(EVALS / "injection" / "direct.jsonl"):
        if "joining" in item.question and item.canary:
            assert item.canary.lower() not in item.question.lower(), item.id


def test_indirect_canaries_all_exist_in_the_poisoned_source() -> None:
    items = load_injection(EVALS / "injection" / "indirect.jsonl")
    assert len(items) == 8 and {i.kind for i in items} == {"indirect"}
    known = set(_load_generator().CANARIES)
    assert {i.canary for i in items} <= known
    assert known == {i.canary for i in items}  # every planted attack has a question


def test_poisoned_pdf_parses_like_a_handbook_chapter(poisoned_pdf: Path) -> None:
    parsed = HandbookPdfParser().parse(poisoned_pdf, POISONED_SOURCE)
    assert parsed.page_count == 4
    assert [e.page.label for e in parsed.elements if e.kind == "text"][0] == "99-1"
    text = "\n".join(e.text for e in parsed.elements)
    for canary in _load_generator().CANARIES:
        assert canary in text


# --- pure logic for the eval database -------------------------------------------------------


def test_create_refuses_existing_target_without_recreate() -> None:
    with pytest.raises(EvalIndexError, match="--recreate"):
        check_create_allowed("rag", "rag_eval", target_exists=True, recreate=False)
    assert check_create_allowed("rag", "rag_eval", target_exists=True, recreate=True) is True
    assert check_create_allowed("rag", "rag_eval", target_exists=False, recreate=False) is False
    assert check_create_allowed("rag", "rag_eval", target_exists=False, recreate=True) is False


def test_create_refuses_to_target_the_source() -> None:
    with pytest.raises(EvalIndexError, match="must differ"):
        check_create_allowed("rag", "rag", target_exists=False, recreate=False)


def test_statements_quote_identifiers() -> None:
    assert create_statement("rag_eval", "rag").as_string() == (
        'CREATE DATABASE "rag_eval" TEMPLATE "rag"'
    )
    # A hostile name stays one quoted identifier; it cannot smuggle a second statement.
    hostile = drop_statement('x"; DROP DATABASE rag; --').as_string()
    assert hostile.startswith('DROP DATABASE IF EXISTS "x""; DROP')  # the quote is doubled
    assert "WITH (FORCE)" in drop_statement("rag_eval").as_string()


def test_in_use_message_explains_the_fix() -> None:
    msg = in_use_message("rag")
    assert "connected" in msg and "uvicorn" in msg


def test_db_name_and_url_rewrite() -> None:
    url = "postgresql://rag:pw@localhost:5433/rag"
    assert db_name(url) == "rag"
    other = with_db(url, "rag_eval")
    assert db_name(other) == EVAL_DB_NAME
    assert "localhost" in other and "5433" in other


# --- against the TEST database only ---------------------------------------------------------


@pytest.mark.db
def test_poisoned_pdf_ingests_and_indirect_questions_retrieve_it(
    db_conn: Conn, poisoned_pdf: Path
) -> None:
    emb = HashingEmbedder()
    assert not poisoned_present(db_conn)
    doc_id = ingest_poisoned(
        db_conn, poisoned_pdf, embedder=emb, describer=CaptionFigureDescriber()
    )
    assert doc_id is not None and poisoned_present(db_conn)
    row = db_conn.execute(
        "SELECT corpus, doc_key FROM documents WHERE id = %s", (doc_id,)
    ).fetchone()
    assert row == ("faa", POISONED_DOC_KEY)

    pipe = RagPipeline(
        db_conn, embedder=emb, reranker=OverlapReranker(), generator=EchoGenerator(), top_k=5
    )
    for item in load_injection(EVALS / "injection" / "indirect.jsonl"):
        run = pipe.run(AskRequest(question=item.question))
        assert item.canary is not None
        assert any(item.canary in p.content for p in run.passages), item.id


@pytest.mark.db
def test_create_eval_database_clones_a_throwaway_source(test_database_url: str) -> None:
    """Exercises the real CREATE DATABASE ... TEMPLATE path on throwaway databases (never
    `rag` or `rag_eval`)."""
    server = test_database_url
    src, dst = "rag_test_tpl_src", "rag_test_tpl_dst"
    assert conninfo_to_dict(server)["dbname"] not in (src, dst)
    admin = with_db(server, "postgres")
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            for name in (src, dst):
                conn.execute(drop_statement(name))
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(src)))
        with psycopg.connect(with_db(server, src), autocommit=True) as conn:
            conn.execute("CREATE TABLE marker (x int)")
        create_eval_database(server, src, dst, recreate=False)
        with psycopg.connect(with_db(server, dst)) as conn:
            assert conn.execute("SELECT to_regclass('marker')").fetchone() == ("marker",)
        with pytest.raises(EvalIndexError, match="already exists"):
            create_eval_database(server, src, dst, recreate=False)
        create_eval_database(server, src, dst, recreate=True)  # drops and re-copies
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            for name in (src, dst):
                conn.execute(drop_statement(name))


@pytest.mark.db
def test_copy_is_refused_with_a_clear_message_while_source_is_in_use(
    test_database_url: str,
) -> None:
    server = test_database_url
    src, dst = "rag_test_tpl_busy", "rag_test_tpl_busy_dst"
    admin = with_db(server, "postgres")
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            for name in (src, dst):
                conn.execute(drop_statement(name))
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(src)))
        # An open session on the source blocks the template copy.
        with (
            psycopg.connect(with_db(server, src)),
            pytest.raises(EvalIndexError, match="connected"),
        ):
            create_eval_database(server, src, dst, recreate=False)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            for name in (src, dst):
                conn.execute(drop_statement(name))
