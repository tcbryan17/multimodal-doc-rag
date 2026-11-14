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

    @field_validator("stats_token", mode="before")
    @classmethod
    def _blank_token_is_unset(cls, value: object) -> object:
        # Same reasoning as the key: a blank `STATS_TOKEN=` must disable /stats, not make the
        # empty string a valid bearer token.
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
    # Hidden reasoning (ADR 0015). Off: measured on FAA figures, it halves cost and latency
    # with equally detailed descriptions, and it can't eat the output cap. The eval compares
    # generation_reasoning on vs off.
    vision_reasoning: bool = False
    generation_reasoning: bool = False

    # The LLM judge for evals (ADR 0011, chosen in ADR 0014). It must come from a different
    # model family than every generator it grades (Claude, Gemma, Qwen) and have a zero-data-
    # retention endpoint. The eval runner refuses a same-family judge, and a blank
    # JUDGE_MODEL= in .env unsets it (the runner then explains why it won't judge).
    judge_model: str | None = "openai/gpt-6-luna"

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
            # Judge candidates (ZDR endpoints, other model families), checked 2026-11-07.
            "openai/gpt-5.4-mini": (0.85, 5.00),
            "openai/gpt-5-mini": (0.30, 2.25),
            "deepseek/deepseek-v4-flash": (0.15, 0.30),
            # The chosen judge (ADR 0014), checked 2026-11-09.
            "openai/gpt-6-luna": (0.10, 0.50),
        }
    )

    @property
    def embedding_key(self) -> str:
        """The `embeddings.model` value: '<model id>@<dimensions>'.

        Each key needs its own partial HNSW index (see migrations/0001_init.sql), so a
        query must filter on exactly this string for the index to be used.
        """
        return f"{self.embedding_model}@{self.embedding_dim}"

    # --- Live-API hardening (docs/governance/control-matrix.md C26, C27, C20) ---------------
    # Origins allowed to call the API from a browser, comma-separated (a plain string, because
    # pydantic-settings would demand JSON for a list). Empty = no CORS headers at all, so only
    # same-origin and non-browser clients work. Intended value: https://tcbryan17.github.io
    cors_allow_origins: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_allow_origins.split(",") if o.strip()]

    # Per-IP limits on /ask (ratelimit.py). 5/min stops scripted bursts but lets a person try
    # a few questions; 60/day bounds one visitor's total spend (~60 x a few tenths of a cent).
    rate_limit_per_minute: int = Field(default=5, ge=1)
    rate_limit_per_day: int = Field(default=60, ge=1)
    # /figures is a cheap read of an image, and each answer links several, so it gets its own
    # far more generous per-minute limit (and no daily one). /health is never limited.
    figures_rate_limit_per_minute: int = Field(default=120, ge=1)
    # How many reverse proxies sit in front of the app (see ratelimit.client_ip). 0 = none:
    # use the TCP peer and ignore X-Forwarded-For, because clients can forge that header.
    trusted_proxy_hops: int = Field(default=0, ge=0)

    # Process-wide cap on live /ask spend per UTC day, in USD (spend.py). Keep it below the
    # provider credit limit (C22) so it trips first.
    daily_spend_cap_usd: float = Field(default=1.0, ge=0)

    # Bearer token for GET /stats. Unset = the endpoint is disabled (404).
    stats_token: SecretStr | None = None

    # Default matches docker-compose.yml; override in .env or the deploy environment.
    database_url: SecretStr = SecretStr("postgresql://rag:rag-dev-only@localhost:5433/rag")


settings = Settings()
