"""損益計算(cardgap.profit)のテスト。

profit.py の docstring に書かれた計算式を手計算した期待値と照合する。
"""

from __future__ import annotations

import pytest

from cardgap.config import Config
from cardgap.profit import compute_profit, profit_for_source


def _cfg() -> Config:
    """config.yaml と同じ構造の dict から直接構築(ファイル非依存)。"""
    return Config(
        {
            "fx": {"conversion_margin": 0.02},
            "ebay_fees": {
                "final_value_fee": 0.1325,
                "per_order_fee_usd": 0.30,
                "international_fee": 0.0135,
                "promoted_listing": 0.02,
            },
            "shipping": {"default_out_jpy": 2500},
            "buy_side": {
                "mercari_fee_rate": 0,
                "mercari_shipping_jpy": 0,
                "snkrdunk_buyer_fee_rate": 0.055,
                "snkrdunk_shipping_jpy": 1000,
            },
        }
    )


def test_compute_profit_matches_hand_calculation():
    # 実効レート = 150 × (1 - 0.02) = 147
    # 売上      = 100 × 147 = 14700
    # 手数料    = 14700 × (0.1325 + 0.0135 + 0.02) + 0.30 × 147 = 2484.3
    # 仕入総額  = 5000 × (1 + 0) + 0 = 5000
    # 利益      = 14700 - 2484.3 - 2500 - 5000 = 4715.7
    # 利益率    = 4715.7 ÷ 5000 = 0.94314
    r = compute_profit(
        median_usd=100.0,
        fx_rate=150.0,
        conversion_margin=0.02,
        final_value_fee=0.1325,
        per_order_fee_usd=0.30,
        international_fee=0.0135,
        promoted_listing=0.02,
        ship_out_jpy=2500.0,
        buy_price_jpy=5000.0,
        buy_fee_rate=0.0,
        buy_shipping_jpy=0.0,
    )
    assert r.revenue_jpy == pytest.approx(14700.0)
    assert r.ebay_fees_jpy == pytest.approx(round(2484.3))    # 丸め後 2484
    assert r.ship_out_jpy == pytest.approx(2500.0)
    assert r.buy_total_jpy == pytest.approx(5000.0)
    assert r.profit_jpy == pytest.approx(round(4715.7))       # 丸め後 4716
    assert r.profit_rate == pytest.approx(0.9431, abs=1e-4)   # 4715.7/5000 を4桁丸め
    assert r.fx_rate == 150.0


def test_profit_for_source_mercari():
    # メルカリは手数料0・送料0 → compute_profit の手計算と同じ結果になる
    r = profit_for_source(_cfg(), "mercari", median_usd=100.0, fx_rate=150.0, buy_price_jpy=5000.0)
    assert r.buy_total_jpy == pytest.approx(5000.0)
    assert r.revenue_jpy == pytest.approx(14700.0)
    assert r.profit_jpy == pytest.approx(4716.0)
    assert r.profit_rate == pytest.approx(0.9431, abs=1e-4)


def test_profit_for_source_snkrdunk_buy_total():
    # スニダンは購入手数料 5.5% + 送料 1000円 が仕入総額に乗る
    r = profit_for_source(_cfg(), "snkrdunk", median_usd=100.0, fx_rate=150.0, buy_price_jpy=10000.0)
    assert r.buy_total_jpy == pytest.approx(10000.0 * 1.055 + 1000.0)  # 11550


def test_profit_for_source_unknown_raises():
    with pytest.raises(ValueError):
        profit_for_source(_cfg(), "yahoo_auction", median_usd=100.0, fx_rate=150.0, buy_price_jpy=1000.0)


def test_zero_buy_total_does_not_divide_by_zero():
    r = compute_profit(
        median_usd=100.0,
        fx_rate=150.0,
        conversion_margin=0.02,
        final_value_fee=0.1325,
        per_order_fee_usd=0.30,
        international_fee=0.0135,
        promoted_listing=0.02,
        ship_out_jpy=2500.0,
        buy_price_jpy=0.0,
        buy_fee_rate=0.0,
        buy_shipping_jpy=0.0,
    )
    assert r.buy_total_jpy == 0.0
    assert r.profit_rate == 0.0
