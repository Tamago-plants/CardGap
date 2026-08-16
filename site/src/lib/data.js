// データ派生ロジック(閾値判定・NEW判定・検索・騰落計算・色スケールなど)。
// JSON の生データはここを通して読み、コンポーネント側に条件式を散らさない。

/** 案件の同一性判定キー(カードID + 仕入元 + 出品URL) */
export function dealKey(deal) {
  return `${deal.card_id}::${deal.source}::${deal.listing_url}`;
}

/** first_seen_at が基準時刻から24時間以内なら NEW */
export function isNewDeal(deal, refIso) {
  if (!deal || !deal.first_seen_at) return false;
  const ref = refIso ? new Date(refIso).getTime() : Date.now();
  const seen = new Date(deal.first_seen_at).getTime();
  if (Number.isNaN(ref) || Number.isNaN(seen)) return false;
  return ref - seen < 24 * 3600 * 1000;
}

/** サマリと同じ「閾値超え」判定(利益率・利益額・信頼度・確度) */
export function isAboveThreshold(deal, thresholds) {
  const t = thresholds || {};
  const minRate = t.min_profit_rate ?? 0.2;
  const minProfit = t.min_profit_jpy ?? 5000;
  return (
    (deal.profit_rate ?? -1) >= minRate &&
    (deal.profit_jpy ?? -1) >= minProfit &&
    deal.reliability === "ok" &&
    (deal.confidence === "high" || deal.confidence === "medium")
  );
}

/** eBay Sold 検索URL(英名 + 型番 + PSA指定) */
export function ebaySoldUrl(cardLike) {
  const parts = [cardLike.name_en || cardLike.name_ja || "", cardLike.card_number || ""];
  if (cardLike.psa_grade) parts.push(`psa ${Math.round(cardLike.psa_grade)}`);
  const q = parts.filter(Boolean).join(" ").trim();
  return `https://www.ebay.com/sch/i.html?_nkw=${encodeURIComponent(q)}&LH_Sold=1&LH_Complete=1`;
}

/** history.cards から card_id → カード のマップを作る */
export function historyByCard(history) {
  const map = new Map();
  for (const c of (history && history.cards) || []) map.set(c.card_id, c);
  return map;
}

/** 直近N日分の中央値配列(スパークライン用)。データが無ければ null */
export function medianSeries(histCard, days = 30) {
  if (!histCard || !histCard.points || histCard.points.length === 0) return null;
  const pts = histCard.points.slice(-days);
  return pts.map((p) => p.median_usd);
}

/**
 * history から「最新 vs 前回」の騰落を全カード分計算する(export.py の movers と同じ規則:
 * 前回が8日より古い・前回中央値0以下は除外)。ランキングの急騰/急落ボード用。
 */
export function computeMovers(history) {
  const out = [];
  for (const c of (history && history.cards) || []) {
    const pts = c.points || [];
    if (pts.length < 2) continue;
    const latest = pts[pts.length - 1];
    const prev = pts[pts.length - 2];
    const gap = (new Date(latest.date) - new Date(prev.date)) / 86400000;
    if (!(gap <= 8) || !(prev.median_usd > 0)) continue;
    out.push({
      card_id: c.card_id,
      display_name: c.display_name,
      category: c.category,
      median_usd: latest.median_usd,
      prev_median_usd: prev.median_usd,
      change_rate: (latest.median_usd - prev.median_usd) / prev.median_usd,
      count: latest.count,
      date: latest.date,
      prev_date: prev.date,
    });
  }
  return out;
}

/**
 * 横断検索インデックス(カード単位)。deals と history の両方からカードを集める。
 * 返り値: [{card_id, display_name, name_ja, name_en, card_number, set_code, category, psa_grade, dealCount}]
 */
export function buildSearchIndex(deals, history) {
  const map = new Map();
  for (const c of (history && history.cards) || []) {
    map.set(c.card_id, { ...c, points: undefined, dealCount: 0 });
  }
  for (const d of (deals && deals.deals) || []) {
    const cur = map.get(d.card_id);
    if (cur) {
      cur.dealCount += 1;
    } else {
      map.set(d.card_id, {
        card_id: d.card_id,
        category: d.category,
        name_ja: d.name_ja,
        name_en: d.name_en,
        set_code: d.set_code,
        card_number: d.card_number,
        psa_grade: d.psa_grade,
        display_name: d.display_name,
        dealCount: 1,
      });
    }
  }
  return Array.from(map.values());
}

/** インクリメンタル検索(カード名・型番・英名の部分一致、スペース区切りAND) */
export function searchCards(index, query, limit = 8) {
  const terms = (query || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [];
  const hay = (c) =>
    [c.display_name, c.name_ja, c.name_en, c.card_number, c.set_code]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
  const out = [];
  for (const c of index) {
    const h = hay(c);
    if (terms.every((t) => h.includes(t))) {
      out.push(c);
      if (out.length >= limit * 3) break; // 余裕を持って集めて後で整列
    }
  }
  // 案件を持つカードを先に
  out.sort((a, b) => (b.dealCount > 0) - (a.dealCount > 0));
  return out.slice(0, limit);
}

/* ---------- 色ユーティリティ(市場マップのダイバージングスケール) ---------- */

function hex2rgb(hex) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function rgb2hex([r, g, b]) {
  return (
    "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("")
  );
}

/** ガンマ2.2で補間(sRGB直線補間の濁りを避ける簡易版) */
function mix(hexA, hexB, t) {
  const a = hex2rgb(hexA);
  const b = hex2rgb(hexB);
  const g = 2.2;
  const c = a.map((av, i) => 255 * Math.pow(
    Math.pow(av / 255, g) * (1 - t) + Math.pow(b[i] / 255, g) * t, 1 / g));
  return rgb2hex(c);
}

/**
 * ダイバージング配色: value(-0.5〜+0.5にクランプ)→ 塗り色。
 * neutral が中点、負は negPole、正は posPole へ補間する。
 */
export function divergingColor(value, { negPole, neutral, posPole, span = 0.5 }) {
  const v = Math.max(-span, Math.min(span, value || 0));
  const t = Math.abs(v) / span;
  // 中心付近を早めに色づける(sqrtで感度を上げる)が中点は中立のまま
  const tt = Math.sqrt(t);
  return v >= 0 ? mix(neutral, posPole, tt) : mix(neutral, negPole, tt);
}

/** 塗り色の輝度からタイル内ラベルのインク(白/黒)を選ぶ */
export function inkFor(hex) {
  const [r, g, b] = hex2rgb(hex).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.35 ? "#12181f" : "#f2f5f9";
}
