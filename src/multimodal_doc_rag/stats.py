"""Ops counters for monitoring (control C27): numbers only, never question content.

Counts since process start and for the current UTC day. In memory and per-process like the
rate limiter, so a restart resets them; for a single-instance demo that is enough to answer
"is it up, is it erroring, is it being abused, what is it costing".
"""

import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime

COUNTERS = (
    "requests",
    "client_errors",  # 4xx (includes rate_limited and 422s)
    "server_errors",  # 5xx (includes budget_blocked)
    "rate_limited",  # 429s from the per-IP limiter
    "budget_blocked",  # 503s because the daily spend cap was reached
    "asks",  # /ask requests that produced an answer
    "idk_answers",  # of those, "I don't know" answers
    "ask_latency_ms_total",  # sum of pipeline time over `asks`; divide for the mean
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Stats:
    def __init__(
        self,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._monotonic = monotonic
        self._started = monotonic()
        self._lock = threading.Lock()
        self._total: Counter[str] = Counter()
        self._today: Counter[str] = Counter()
        self._day: date = clock().date()

    def incr(self, name: str, amount: int = 1) -> None:
        assert name in COUNTERS, name
        with self._lock:
            self._roll()
            self._total[name] += amount
            self._today[name] += amount

    def count_response(self, status: int) -> None:
        self.incr("requests")
        if 400 <= status < 500:
            self.incr("client_errors")
        elif status >= 500:
            self.incr("server_errors")

    def _roll(self) -> None:
        today = self._clock().date()
        if today != self._day:
            self._day = today
            self._today = Counter()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._roll()
            return {
                "uptime_s": int(self._monotonic() - self._started),
                "since_start": {n: self._total[n] for n in COUNTERS},
                "today": {"date": self._day.isoformat(), **{n: self._today[n] for n in COUNTERS}},
            }
