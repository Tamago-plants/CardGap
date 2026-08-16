// 損益モデル(cardgap/profit.py と同一式のJS再現)。
// summary.json の profit_model パラメータを受け取り、What-if シミュレータと
// ドロワーの損益ブレークダウンで使う。式を変えるときは Python 側と同時に直すこと。
//
//   実効レート    = fx × (1 - conversion_margin)
//   想定売上JPY   = 売却USD × 実効レート
//   eBay手数料JPY = 売上 × (FVF + intl + promo) + per_order_fee_usd × 実効レート
//   仕入総額JPY   = 仕入価格 × (1 + 仕入手数料率) + 仕入送料
//   実質利益JPY   = 売上 - eBay手数料 - 発送送料 - 仕入総額

/** 仕入元別の手数料パラメータ({fee_rate, shipping_jpy})。未知の仕入元は手数料ゼロ扱い。 */
export function buySideParams(model, source) {
  const buy = (model && model.buy) || {};
  return buy[source] || { fee_rate: 0, shipping_jpy: 0 };
}

/**
 * 損益計算。model=summary.profit_model, source=仕入元キー。
 * 返り値はすべて円(rate だけ比率)。
 */
export function computeProfit({ usd, buyJpy, fx, model, source }) {
  const m = model || {};
  const effective = fx * (1 - (m.conversion_margin ?? 0.02));
  const revenue = (usd || 0) * effective;
  const feeRate =
    (m.final_value_fee ?? 0.1325) + (m.international_fee ?? 0.0135) + (m.promoted_listing ?? 0.02);
  const fees = revenue * feeRate + (m.per_order_fee_usd ?? 0.3) * effective;
  const shipOut = m.ship_out_jpy ?? 2500;
  const side = buySideParams(m, source);
  const buyTotal = (buyJpy || 0) * (1 + (side.fee_rate || 0)) + (side.shipping_jpy || 0);
  const profit = revenue - fees - shipOut - buyTotal;
  const rate = buyTotal > 0 ? profit / buyTotal : 0;
  return {
    revenue: Math.round(revenue),
    fees: Math.round(fees),
    shipOut: Math.round(shipOut),
    buyTotal: Math.round(buyTotal),
    profit: Math.round(profit),
    rate,
  };
}

/** 損益分岐となる仕入価格の上限(この価格で買うと利益0)。 */
export function breakevenBuy({ usd, fx, model, source }) {
  const m = model || {};
  const effective = fx * (1 - (m.conversion_margin ?? 0.02));
  const revenue = (usd || 0) * effective;
  const feeRate =
    (m.final_value_fee ?? 0.1325) + (m.international_fee ?? 0.0135) + (m.promoted_listing ?? 0.02);
  const fees = revenue * feeRate + (m.per_order_fee_usd ?? 0.3) * effective;
  const shipOut = m.ship_out_jpy ?? 2500;
  const side = buySideParams(m, source);
  const maxBuyTotal = revenue - fees - shipOut;
  const buy = (maxBuyTotal - (side.shipping_jpy || 0)) / (1 + (side.fee_rate || 0));
  return Math.max(0, Math.floor(buy));
}
