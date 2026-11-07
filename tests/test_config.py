import pytest

from multimodal_doc_rag.config import Settings


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_openrouter_key_counts_as_unset(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", raw)
    assert Settings(_env_file=None).openrouter_api_key is None  # type: ignore[call-arg]


def test_real_key_is_kept_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    key = Settings(_env_file=None).openrouter_api_key  # type: ignore[call-arg]
    assert key is not None and key.get_secret_value() == "sk-or-test"
    assert "sk-or-test" not in repr(key)


def test_embedding_key_format() -> None:
    s = Settings(_env_file=None, embedding_model="m/x", embedding_dim=8)  # type: ignore[call-arg]
    assert s.embedding_key == "m/x@8"
