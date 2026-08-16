"""相場集計(cardgap.stats.compute_market_stats)のテスト。"""

from __future__ import annotations

import pytest

from cardgap.models import RELIABILITY_LOW, RELIABILITY_OK
from cardgap.stats import compute_market_stats


def test_median_odd_count():
    s = compute_market_stats([30.0, 10.0, 20.0], min_sold_count=3)
    assert s is not None
    assert s.median_usd == pytest.approx(20.0)
    assert s.count == 3
    assert s.min_usd == pytest.approx(10.0)
    assert s.max_usd == pytest.approx(30.0)


def test_median_even_count():
    # 偶数個は中央2値の平均
    s = compute_market_stats([10.0, 20.0, 30.0, 40.0], min_sold_count=3)
    assert s is not None
    assert s.median_usd == pytest.approx(25.0)
    assert s.count == 4


def test_reliability_low_when_count_below_threshold():
    s = compute_market_stats([100.0, 120.0], min_sold_count=3)
    assert s is not None
    assert s.reliability == RELIABILITY_LOW


def test_reliability_ok_when_count_at_threshold():
    s = compute_market_stats([100.0, 120.0, 110.0], min_sold_count=3)
    assert s is not None
    assert s.reliability == RELIABILITY_OK


def test_empty_list_returns_none():
    assert compute_market_stats([], min_sold_count=3) is None


def test_zero_negative_and_none_values_are_excluded():
    # 0円・負値・None はノイズとして除外して集計する
    s = compute_market_stats([0.0, -5.0, None, 10.0, 20.0], min_sold_count=3)
    assert s is not None
    assert s.count == 2
    assert s.median_usd == pytest.approx(15.0)
    assert s.min_usd == pytest.approx(10.0)
    assert s.reliability == RELIABILITY_LOW


def test_all_invalid_values_returns_none():
    assert compute_market_stats([0.0, -1.0, None], min_sold_count=1) is None
