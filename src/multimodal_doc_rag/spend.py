"""A process-wide, per-UTC-day spending cap for the live `/ask` (control C26).

This reuses `CostMeter` (models/cost.py): the OpenRouter client already calls `meter.check()`
before every request and `meter.record()` after it, and `CostMeter` already charges a reported
cost, else tokens x our price table, else a pessimistic flat amount. So the live cap fails
closed exactly like the ingest and eval caps. Two things the offline meter does not need but a
server does:

- it is shared by many request threads, so `check` and `record` take a lock;
- the budget resets each UTC day, so every call first rolls the meter over if the date changed.

The check runs before each model call, so a request that starts just under the cap can still
finish its remaining calls (one `/ask` is ~3 calls, a few tenths of a cent), and concurrent
requests can overshoot by a few calls. Set the cap a little below what you can afford to lose.
The provider-side credit limit (C22) remains the hard backstop.

Per-process, like the rate limiter: a restart forgets today's spend. After a mid-day restart
the cap can be spent again, so the worst case is one cap per restart; the provider limit
bounds that.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from multimodal_doc_rag.models.cost import CostMeter


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class DailyCostMeter(CostMeter):
    clock: Callable[[], datetime] = _utc_now
    _day: date | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def _roll(self) -> None:
        """Start a fresh day if the UTC date changed. Caller holds the lock."""
        today = self.clock().date()
        if today != self._day:
            self._day = today
            self.spent_usd = 0.0
            self.calls = self.reported_calls = self.estimated_calls = self.unpriced_calls = 0

    def check(self) -> None:
        with self._lock:
            self._roll()
            super().check()

    def record(self, model: str | None, usage: Any) -> float:
        with self._lock:
            self._roll()
            return super().record(model, usage)

    def spent_today(self) -> float:
        with self._lock:
            self._roll()
            return self.spent_usd

    def exhausted(self) -> bool:
        with self._lock:
            self._roll()
            return self.spent_usd >= self.cap_usd

    def seconds_until_reset(self) -> int:
        now = self.clock()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)
        return max(1, int((midnight - now).total_seconds()))
