"""Spend tracking with a hard cap, shared by ingest and the eval runner.

Why this fails *closed*: OpenRouter normally reports each call's price in `usage.cost`, but
that hasn't been verified live for every endpoint (embeddings, rerank). A cap that only summed
reported costs would silently never trip if a response came back without one. So each call is
charged, in order of preference:
  1. the cost OpenRouter reported;
  2. otherwise, its token counts × a price from our table (`Settings.model_prices`);
  3. otherwise, a pessimistic flat amount per call (`unpriced_call_usd`).
Over-counting only stops a run early; under-counting could spend real money.

The check happens BEFORE each request, so a run can overshoot the cap by at most one call.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class BudgetExceededError(RuntimeError):
    """The run hit its spending cap.

    Deliberately NOT an OpenRouterError: code that degrades on provider errors (the rerank
    fallback, caption-only figures) must not swallow this. Callers re-raise it explicitly.
    """


@dataclass(frozen=True)
class Price:
    input_per_m: float  # USD per million input (prompt) tokens
    output_per_m: float = 0.0  # USD per million output tokens; 0 for embeddings


@dataclass
class CostMeter:
    cap_usd: float
    prices: Mapping[str, Price] = field(default_factory=dict)
    unpriced_call_usd: float = 0.005
    spent_usd: float = 0.0
    calls: int = 0
    reported_calls: int = 0  # calls where OpenRouter told us the price
    estimated_calls: int = 0  # priced from tokens × our table
    unpriced_calls: int = 0  # charged the flat pessimistic amount

    def check(self) -> None:
        """Raise before a request if the cap is already reached."""
        if self.spent_usd >= self.cap_usd:
            raise BudgetExceededError(
                f"spending cap reached: ${self.spent_usd:.4f} of ${self.cap_usd:.2f} "
                f"after {self.calls} calls"
            )

    def record(self, model: str | None, usage: Any) -> float:
        """Charge one completed call; returns what was charged."""
        self.calls += 1
        usage = usage if isinstance(usage, dict) else {}
        cost = usage.get("cost")
        if isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0:
            charged = float(cost)
            self.reported_calls += 1
        elif (price := self.prices.get(model or "")) is not None and _has_tokens(usage):
            charged = (
                _tokens(usage, "prompt_tokens") * price.input_per_m
                + _tokens(usage, "completion_tokens") * price.output_per_m
            ) / 1_000_000
            self.estimated_calls += 1
        else:
            charged = self.unpriced_call_usd
            self.unpriced_calls += 1
        self.spent_usd += charged
        return charged

    def summary(self) -> str:
        return (
            f"${self.spent_usd:.4f} of ${self.cap_usd:.2f} cap over {self.calls} calls "
            f"({self.reported_calls} reported, {self.estimated_calls} estimated from tokens, "
            f"{self.unpriced_calls} charged the flat fallback)"
        )


def _tokens(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def _has_tokens(usage: dict[str, Any]) -> bool:
    return _tokens(usage, "prompt_tokens") > 0 or _tokens(usage, "completion_tokens") > 0
