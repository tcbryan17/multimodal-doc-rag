"""App settings, loaded from environment variables or a local .env file."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SecretStr keeps the key out of logs and reprs. Optional for now so tests and the
    # /health route run without it; model-calling code should fail fast if it's missing.
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_s: float = 30.0

    # Model IDs live here, never in code (ADR 0009).
    embedding_model: str = "qwen/qwen3-embedding-8b"
    embedding_dim: int = 1024
    rerank_model: str = "qwen/qwen3-reranker-8b"
    generation_model: str = "anthropic/claude-haiku-5.5"

    # Default matches docker-compose.yml; override in .env or the deploy environment.
    database_url: SecretStr = SecretStr("postgresql://rag:rag-dev-only@localhost:5433/rag")


settings = Settings()
