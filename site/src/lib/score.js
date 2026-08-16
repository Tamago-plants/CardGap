// Opportunity Score(全画面共通の 0-100 スコア)。
// score = round(100 × clamp(rate/0.5,0,1) × clamp(count/10,0.2,1) × conf_w × rel_w)
// マイナス利益は一律 0。ここ以外でスコアを計算しないこと。

const CONF_W = { high: 1, medium: 0.75, low: 0.45 };
const REL_W = { ok: 1, low: 0.5 };

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** スコアの内訳(ツールチップ表示用)。 */
export function scoreParts(deal) {
  if (!deal || deal.profit_jpy == null || deal.profit_jpy < 0) {
    return { rateF: 0, liqF: 0, confW: 0, relW: 0, score: 0, negative: true };
  }
  const rateF = clamp((deal.profit_rate || 0) / 0.5, 0, 1);
  const liqF = clamp((deal.ebay_count_30d || 0) / 10, 0.2, 1);
  const confW = CONF_W[deal.confidence] ?? 0.45;
  const relW = REL_W[deal.reliability] ?? 0.5;
  return {
    rateF,
    liqF,
    confW,
    relW,
    score: Math.round(100 * rateF * liqF * confW * relW),
    negative: false,
  };
}

export function opportunityScore(deal) {
  return scoreParts(deal).score;
}

/** スコア帯(バッジの色段階): high / mid / low / zero */
export function scoreTier(score) {
  if (score >= 60) return "high";
  if (score >= 35) return "mid";
  if (score >= 15) return "low";
  return "zero";
}
