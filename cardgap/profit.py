"""損益計算モデル。config.yaml の値をそのまま式に落とす。

計算式(README にも同じものを記載):
  実効レート        = USD/JPY × (1 - conversion_margin)
  想定売上JPY       = eBay売却中央値USD × 実効レート
  eBay手数料JPY     = 想定売上 × (FVF + international_fee + promoted)
                      + per_order_fee_usd × 実効レート
  仕入総額JPY       = 仕入価格 × (1 + 仕入手数料率) + 仕入送料
  実質利益JPY       = 想定売上 - eBay手数料 - 発送送料 - 仕入総額
  利益率            = 実質利益 ÷ 仕入総額
"""

from __future__ import annotations

from .config import Config
from .models import ProfitResult


def compute_profit(
    *,
    median_usd: float,
    fx_rate: float,
    conversion_margin: float,
    final_value_fee: float,
    per_order_fee_usd: float,
    international_fee: float,
    promoted_listing: float,
    ship_out_jpy: float,
    buy_price_jpy: float,
    buy_fee_rate: float,
    buy_shipping_jpy: float,
) -> ProfitResult:
    effective_rate = fx_rate * (1.0 - conversion_margin)
    revenue_jpy = median_usd * effective_rate
    fee_rate = final_value_fee + international_fee + promoted_listing
    ebay_fees_jpy = revenue_jpy * fee_rate + per_order_fee_usd * effective_rate
    buy_total_jpy = buy_price_jpy * (1.0 + buy_fee_rate) + buy_shipping_jpy
    profit_jpy = revenue_jpy - ebay_fees_jpy - ship_out_jpy - buy_total_jpy
    profit_rate = profit_jpy / buy_total_jpy if buy_total_jpy > 0 else 0.0
    return ProfitResult(
        revenue_jpy=round(revenue_jpy, 0),
        ebay_fees_jpy=round(ebay_fees_jpy, 0),
        ship_out_jpy=ship_out_jpy,
        buy_total_jpy=round(buy_total_jpy, 0),
        profit_jpy=round(profit_jpy, 0),
        profit_rate=round(profit_rate, 4),
        fx_rate=fx_rate,
    )


def profit_for_source(
    cfg: Config, source: str, median_usd: float, fx_rate: float, buy_price_jpy: float
) -> ProfitResult:
    """config.yaml から仕入れ元別の手数料を引いて compute_profit を呼ぶ。"""
    if source == "mercari":
        buy_fee_rate = float(cfg.get("buy_side.mercari_fee_rate", 0.0))
        buy_shipping = float(cfg.get("buy_side.mercari_shipping_jpy", 0))
    elif source == "snkrdunk":
        buy_fee_rate = float(cfg.get("buy_side.snkrdunk_buyer_fee_rate", 0.055))
        buy_shipping = float(cfg.get("buy_side.snkrdunk_shipping_jpy", 1000))
    else:
        raise ValueError(f"unknown source: {source}")
    return compute_profit(
        median_usd=median_usd,
        fx_rate=fx_rate,
        conversion_margin=float(cfg.get("fx.conversion_margin", 0.02)),
        final_value_fee=float(cfg.get("ebay_fees.final_value_fee", 0.1325)),
        per_order_fee_usd=float(cfg.get("ebay_fees.per_order_fee_usd", 0.30)),
        international_fee=float(cfg.get("ebay_fees.international_fee", 0.0135)),
        promoted_listing=float(cfg.get("ebay_fees.promoted_listing", 0.02)),
        ship_out_jpy=float(cfg.get("shipping.default_out_jpy", 2500)),
        buy_price_jpy=buy_price_jpy,
        buy_fee_rate=buy_fee_rate,
        buy_shipping_jpy=buy_shipping,
    )
