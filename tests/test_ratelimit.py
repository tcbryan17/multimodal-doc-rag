from starlette.requests import Request

from multimodal_doc_rag.ratelimit import DAY_S, SlidingWindowLimiter, client_ip


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_per_minute_limit_then_retry_after_then_recovers() -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(2, clock=clock)
    assert limiter.check("a").allowed
    clock.now += 10
    assert limiter.check("a").allowed
    blocked = limiter.check("a")
    assert not blocked.allowed
    assert blocked.retry_after_s == 50  # the first hit ages out 60s after it was made
    clock.now += 50
    assert limiter.check("a").allowed


def test_ips_have_separate_buckets() -> None:
    limiter = SlidingWindowLimiter(1, clock=Clock())
    assert limiter.check("a").allowed
    assert not limiter.check("a").allowed
    assert limiter.check("b").allowed


def test_per_day_limit_outlasts_the_minute_window() -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(5, per_day=3, clock=clock)
    for _ in range(3):
        assert limiter.check("a").allowed
        clock.now += 120
    blocked = limiter.check("a")
    assert not blocked.allowed
    assert blocked.retry_after_s > 3600  # waiting out the day window, not the minute one
    clock.now += DAY_S
    assert limiter.check("a").allowed


def test_rejected_requests_do_not_extend_the_wait() -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(1, clock=clock)
    limiter.check("a")
    clock.now += 30
    for _ in range(10):
        assert not limiter.check("a").allowed
    clock.now += 30
    assert limiter.check("a").allowed


def test_tracked_ips_are_bounded() -> None:
    limiter = SlidingWindowLimiter(1, clock=Clock(), max_tracked=3)
    for i in range(10):
        limiter.check(f"ip{i}")
    assert len(limiter._hits) == 3


def _request(peer: str | None, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


def test_forwarded_header_is_ignored_by_default() -> None:
    assert client_ip(_request("10.0.0.1", "6.6.6.6"), 0) == "10.0.0.1"


def test_trusted_hops_take_the_nth_entry_from_the_right() -> None:
    # The client forged "6.6.6.6"; our one proxy appended the address it really saw.
    assert client_ip(_request("10.0.0.1", "6.6.6.6, 203.0.113.9"), 1) == "203.0.113.9"
    assert client_ip(_request("10.0.0.1", "6.6.6.6, 203.0.113.9, 10.1.1.1"), 2) == "203.0.113.9"


def test_missing_or_short_header_falls_back_to_the_peer() -> None:
    assert client_ip(_request("10.0.0.1"), 1) == "10.0.0.1"
    assert client_ip(_request("10.0.0.1", "203.0.113.9"), 2) == "10.0.0.1"
    assert client_ip(_request(None), 0) == "unknown"
