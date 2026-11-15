"""Per-IP rate limiting for the live API (control C26), hand-rolled and in memory.

Why hand-rolled: the whole need is "N requests per minute and M per day per client", which is
~60 lines. A library (slowapi etc.) would add a dependency, and the interesting part, deciding
whose IP to trust, we have to write ourselves anyway.

**Per-process.** The counts live in this process's memory. That is correct only while the API
runs as a single instance (the deployment plan). With two instances each would allow the full
quota, so scaling out means moving the counts to a shared store (or limiting at the proxy).
A restart also forgets everyone's counts; for a demo that is an accepted weakness, and the
daily spend cap (spend.py) still bounds the money.

Algorithm: a sliding-window log. For each IP we keep the timestamps of its *accepted* requests
and count how many fall inside the last minute / last day. Unlike a fixed window it has no
burst-at-the-boundary loophole, and it can say exactly how long until the next request is
allowed (`Retry-After`). Rejected requests are not recorded, so hammering a 429 does not
extend your own ban.
"""

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

MINUTE_S = 60.0
DAY_S = 86_400.0
# Bound on distinct IPs remembered. Without it, a client rotating source addresses (easy over
# IPv6) could grow the table without limit. Least-recently-seen IPs are dropped first.
MAX_TRACKED_IPS = 10_000


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_s: int = 0  # whole seconds, >= 1 when not allowed


class SlidingWindowLimiter:
    def __init__(
        self,
        per_minute: int,
        per_day: int | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_tracked: int = MAX_TRACKED_IPS,
    ) -> None:
        if per_minute < 1 or (per_day is not None and per_day < 1):
            raise ValueError("rate limits must be at least 1")
        self._per_minute = per_minute
        self._per_day = per_day
        self._clock = clock
        self._max_tracked = max_tracked
        # FastAPI runs sync routes in a thread pool, so two requests can reach this at once;
        # the lock makes check-then-record atomic (no two threads both take the last slot).
        self._lock = threading.Lock()
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, key: str) -> Decision:
        """Record the request and allow it, or refuse it and say when to retry."""
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = self._hits[key] = deque()
                while len(self._hits) > self._max_tracked:
                    self._hits.popitem(last=False)  # evict the least recently seen IP
            else:
                self._hits.move_to_end(key)
            while hits and now - hits[0] >= DAY_S:
                hits.popleft()  # older than any window we count

            waits: list[float] = []
            recent = [t for t in hits if now - t < MINUTE_S]
            if len(recent) >= self._per_minute:
                # Free again when the oldest hit in the window ages out.
                waits.append(recent[0] + MINUTE_S - now)
            if self._per_day is not None and len(hits) >= self._per_day:
                waits.append(hits[0] + DAY_S - now)
            if waits:
                return Decision(False, max(1, math.ceil(max(waits))))
            hits.append(now)
            return Decision(True)


def client_ip(request: Request, trusted_proxy_hops: int) -> str:
    """The address to rate-limit.

    Default (0 hops): the TCP peer, `request.client.host`. That is the only address a client
    cannot fake. `X-Forwarded-For` is just a header: anyone can send `X-Forwarded-For: 1.2.3.4`
    and, if we believed it, take a fresh rate-limit bucket on every request.

    Behind a reverse proxy the peer is the proxy for every visitor, so we must read the header.
    Each trusted proxy *appends* the address it saw to the right of the list, so the entries
    the client invented are on the left and the ones our own infrastructure wrote are on the
    right. With `trusted_proxy_hops = N` we take the Nth entry from the right: the address
    seen by the outermost proxy we control. Set N to the real number of proxies in front of
    the app (1 for a single platform load balancer); too high lets a client choose its own
    bucket, too low limits the proxy as if it were one visitor. If the header has fewer
    entries than N (it was bypassed or is missing), fall back to the peer address.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return peer
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) < trusted_proxy_hops:
        return peer
    return parts[-trusted_proxy_hops]
