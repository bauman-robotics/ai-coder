from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from ai_coder.config import PeakSchedule, PeakWindow, PricePair, ModelPricing
from ai_coder.pricing import Rate, calculate_cost, is_peak_now


# ---------- is_peak_now ----------

def _schedule():
    return PeakSchedule(
        timezone="UTC",
        weekdays_only=True,
        windows=[
            PeakWindow(start="01:00", end="04:00"),
            PeakWindow(start="06:00", end="10:00"),
        ],
        display_timezone="Europe/Moscow",
    )


@pytest.mark.parametrize("hour,expected", [
    (2, True),    # внутри 01:00–04:00
    (3, True),
    (7, True),    # внутри 06:00–10:00
    (5, False),   # между окнами
    (11, False),  # после второго окна
    (0, False),   # до первого окна
])
def test_is_peak_windows(hour, expected):
    sched = _schedule()
    fake_now = datetime(2026, 10, 7, hour, 30, tzinfo=ZoneInfo("UTC"))  # среда
    with patch("ai_coder.pricing.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        is_peak, _ = is_peak_now(sched)
    assert is_peak is expected


def test_is_peak_weekend_off():
    sched = _schedule()
    # суббота 02:00 UTC — внутри окна, но выходной
    fake_now = datetime(2026, 10, 10, 2, 30, tzinfo=ZoneInfo("UTC"))
    with patch("ai_coder.pricing.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        is_peak, _ = is_peak_now(sched)
    assert is_peak is False


# ---------- calculate_cost ----------

def _pricing():
    return ModelPricing(
        cache_hit_per_1m_cny=PricePair(off_peak=0.02, peak=0.04),
        cache_miss_per_1m_cny=PricePair(off_peak=1.0, peak=2.0),
        output_per_1m_cny=PricePair(off_peak=4.0, peak=8.0),
    )


def _rate(value, source="config"):
    return Rate(value=value, source=source, fetched_at=0)


def test_calculate_cost_off_peak_miss_only():
    cost = calculate_cost(
        pricing=_pricing(),
        is_peak=False,
        peak_window=None,
        prompt_hit_tokens=0,
        prompt_miss_tokens=1_000_000,
        completion_tokens=1_000_000,
        cny_to_rub=_rate(12.5),
        usd_to_rub=_rate(90.0),
    )
    # 1.0 + 4.0 = 5.0 CNY
    assert cost.cost_cny == pytest.approx(5.0)
    assert cost.cost_rub == pytest.approx(62.5)
    assert cost.cost_usd == pytest.approx(62.5 / 90.0)


def test_calculate_cost_peak_doubles():
    off = calculate_cost(
        pricing=_pricing(), is_peak=False, peak_window=None,
        prompt_hit_tokens=0, prompt_miss_tokens=1_000_000,
        completion_tokens=1_000_000,
        cny_to_rub=_rate(1.0), usd_to_rub=_rate(1.0),
    )
    peak = calculate_cost(
        pricing=_pricing(), is_peak=True, peak_window="01:00-04:00 UTC",
        prompt_hit_tokens=0, prompt_miss_tokens=1_000_000,
        completion_tokens=1_000_000,
        cny_to_rub=_rate(1.0), usd_to_rub=_rate(1.0),
    )
    assert peak.cost_cny == pytest.approx(off.cost_cny * 2)


def test_calculate_cost_with_cache_hit():
    cost = calculate_cost(
        pricing=_pricing(), is_peak=False, peak_window=None,
        prompt_hit_tokens=1_000_000,
        prompt_miss_tokens=0,
        completion_tokens=0,
        cny_to_rub=_rate(1.0), usd_to_rub=_rate(1.0),
    )
    # 1M hit * 0.02 = 0.02 CNY
    assert cost.cost_cny == pytest.approx(0.02)
