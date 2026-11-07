"""App settings, loaded from environment variables or a local .env file."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SecretStr keeps the key out of logs and reprs. Optional for now so tests and the
    # /health route run without it; model-calling code should fail fast if it's missing.
    openrouter_api_key: SecretStr | None = None

    @field_validator("openrouter_api_key", mode="before")
    @classmethod
    def _blank_key_is_unset(cls, value: object) -> object:
        # `.env.example` ships `OPENROUTER_API_KEY=`; a copied blank line must mean "no key"
        # (so /ask answers 503), not an empty key that gets sent to OpenRouter.
        return None if isinstance(value, str) and not value.strip() else value

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_s: float = 30.0

    # SEC fair-access policy requires a User-Agent that names a real contact ("Jane Doe
    # jane@example.com"). The owner picks it; there is deliberately no default, and EDGAR
    # fetching fails fast when it is unset.
    sec_user_agent: str | None = None
    # Where fetch scripts put downloaded source documents (gitignored).
    data_dir: Path = Path("data")

    # Model IDs live here, never in code (ADR 0009).
    embedding_model: str = "qwen/qwen3-embedding-8b"
    embedding_dim: int = 1024
    rerank_model: str = "qwen/qwen3-reranker-8b"
    generation_model: str = "anthropic/claude-haiku-5.5"
    # Describes figures at ingest (ADR 0008). Same default as the generator; the eval may
    # pick a different one.
    vision_model: str = "anthropic/claude-haiku-5.5"

    # The LLM judge for evals (ADR 0011). Deliberately no default: it must come from a
    # different model family than every generator it grades (Claude, Gemma, Qwen), and must
    # have a zero-data-retention endpoint. The owner chooses it; the eval runner refuses to
    # judge until it's set.
    judge_model: str | None = None

    # Spending caps in USD, enforced by models/cost.py. Keep them below the key's own credit
    # limit, so our cap trips first with a clear message.
    ingest_budget_usd: float = 3.0
    eval_budget_usd: float = 2.0
    # Charged per call when OpenRouter reports no cost and the model isn't in model_prices.
    unpriced_call_usd: float = 0.005
    # Fallback prices (USD per million input / output tokens), used only when a response has
    # no `usage.cost`. From ADR 0009 (checked 2026-11-07), rounded UP so estimates err high.
    model_prices: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "qwen/qwen3-embedding-8b": (0.02, 0.0),
            "openai/text-embedding-3-small": (0.03, 0.0),
            "anthropic/claude-haiku-5.5": (0.15, 0.75),
            "google/gemma-4-26b": (0.06, 0.20),
            "qwen/qwen3.6-35b-a3b": (0.02, 0.15),
        }
    )

    @property
    def embedding_key(self) -> str:
        """The `embeddings.model` value: '<model id>@<dimensions>'.

        Each key needs its own partial HNSW index (see migrations/0001_init.sql), so a
        query must filter on exactly this string for the index to be used.
        """
        return f"{self.embedding_model}@{self.embedding_dim}"

    # Default matches docker-compose.yml; override in .env or the deploy environment.
    database_url: SecretStr = SecretStr("postgresql://rag:rag-dev-only@localhost:5433/rag")


settings = Settings()
