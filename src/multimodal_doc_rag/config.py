"""App settings, loaded from environment variables or a local .env file."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SecretStr keeps the key out of logs and reprs. Optional for now so tests and the
    # /health route run without it; model-calling code should fail fast if it's missing.
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Default matches docker-compose.yml; override in .env or the deploy environment.
    database_url: SecretStr = SecretStr("postgresql://rag:rag-dev-only@localhost:5433/rag")


settings = Settings()
