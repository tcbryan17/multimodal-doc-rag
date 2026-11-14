from datetime import UTC, datetime, timedelta

import pytest

from multimodal_doc_rag.models.cost import BudgetExceededError, Price
from multimodal_doc_rag.spend import DailyCostMeter


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 14, 23, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_meter_trips_at_the_cap_and_resets_at_utc_midnight() -> None:
    clock = Clock()
    meter = DailyCostMeter(cap_usd=1.0, clock=clock)
    meter.check()
    meter.record("m", {"cost": 1.0})
    assert meter.exhausted()
    with pytest.raises(BudgetExceededError):
        meter.check()
    assert meter.seconds_until_reset() == 3600
    clock.now += timedelta(hours=1)  # 00:00 UTC next day
    assert not meter.exhausted()
    assert meter.spent_today() == 0.0
    meter.check()


def test_meter_reuses_cost_meter_pricing() -> None:
    meter = DailyCostMeter(cap_usd=1.0, prices={"m": Price(1.0, 2.0)}, clock=Clock())
    charged = meter.record("m", {"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
    assert charged == pytest.approx(2.0)
    assert meter.estimated_calls == 1
