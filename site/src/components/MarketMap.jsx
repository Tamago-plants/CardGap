// 市場マップ: squarified treemap(手書きSVG)。
// 面積 = eBay中央値USD × 30日件数(≒月間流通規模)、
// 色 = 最良案件の利益率のダイバージング(負=赤 / 0=中立グレー / 正=緑)。
// 案件が無いカード(履歴のみ)は中立色 + 斜線テクスチャで区別する。
import { useMemo, useRef, useState } from "react";
import { squarify } from "../lib/treemap.js";
import { divergingColor, inkFor } from "../lib/data.js";
import { categoryLabel, fmtPct, fmtSignedPct, fmtUsd } from "../lib/format.js";
import { opportunityScore } from "../lib/score.js";

// palette.md のダイバージング用ステップ(light/dark)。中点は中立グレー
const POLES = {
  dark: { negPole: "#e66767", neutral: "#383835", posPole: "#0ca30c" },
  light: { negPole: "#d03b3b", neutral: "#f0efec", posPole: "#0ca30c" },
};

const VBW = 1000;
const VBH = 560;

/** CJK混在文字列をおおよその描画幅(px)で切り詰める(全角≒fs、半角≒0.55fs) */
function truncateToWidth(s, maxPx, fs = 13) {
  let w = 0;
  let out = "";
  for (const ch of s || "") {
    const cw = ch.charCodeAt(0) > 0x2e7f ? fs : fs * 0.58;
    if (w + cw > maxPx) return out + "…";
    w += cw;
    out += ch;
  }
  return out;
}

export default function MarketMap({ deals, history, theme, params, setParams, onOpenCard }) {
  const wrapRef = useRef(null);
  const [tip, setTip] = useState(null); // {x, y, node}
  const catFilter = params.cat || "all";
  const poles = POLES[theme] || POLES.dark;

  // カード単位に集計: 面積は流通規模、色は最良案件の利益率
  const nodes = useMemo(() => {
    const bestDeal = new Map();
    for (const d of deals) {
      const cur = bestDeal.get(d.card_id);
      if (!cur || (d.profit_rate || -9) > (cur.profit_rate || -9)) bestDeal.set(d.card_id, d);
    }
    const out = [];
    for (const c of (history && history.cards) || []) {
      const pts = c.points || [];
      if (pts.length === 0) continue;
      const latest = pts[pts.length - 1];
      const count30 = pts.slice(-30).reduce((a, p) => a + (p.count || 0), 0);
      const size = (latest.median_usd || 0) * count30;
      if (size <= 0) continue;
      const deal = bestDeal.get(c.card_id) || null;
      out.push({
        card_id: c.card_id,
        name: c.display_name,
        category: c.category,
        value: size,
        median: latest.median_usd,
        count30,
        deal,
        rate: deal ? deal.profit_rate : null,
      });
    }
    // 案件だけあって履歴が無いカードも面積を仕入価格ベースで補完(0件で壊さない)
    for (const [cardId, d] of bestDeal) {
      if (!out.some((n) => n.card_id === cardId)) {
        const size = (d.ebay_median_usd || 0) * (d.ebay_count_30d || 0);
        if (size > 0) {
          out.push({
            card_id: cardId,
            name: d.display_name,
            category: d.category,
            value: size,
            median: d.ebay_median_usd,
            count30: d.ebay_count_30d,
            deal: d,
            rate: d.profit_rate,
          });
        }
      }
    }
    return out;
  }, [deals, history]);

  const categories = useMemo(() => {
    const set = new Set(nodes.map((n) => n.category).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [nodes]);

  const filtered = catFilter === "all" ? nodes : nodes.filter((n) => n.category === catFilter);
  const tiles = useMemo(
    () => squarify(filtered.slice().sort((a, b) => b.value - a.value), 0, 0, VBW, VBH),
    [filtered]
  );

  const showTip = (e, node) => {
    const rect = wrapRef.current.getBoundingClientRect();
    setTip({
      x: Math.min(e.clientX - rect.left + 14, rect.width - 190),
      y: e.clientY - rect.top + 14,
      node,
    });
  };

  // 凡例グラデ用ストップ
  const stops = [-0.5, -0.25, 0, 0.25, 0.5].map((v) => ({
    off: `${((v + 0.5) / 1) * 100}%`,
    color: divergingColor(v, poles),
  }));

  return (
    <div className="card treemap-card">
      <div className="tm-toolbar" role="group" aria-label="カテゴリフィルタ">
        {categories.map((c) => (
          <button
            key={c}
            type="button"
            className={`filter-chip${catFilter === c ? " active" : ""}`}
            onClick={() => setParams({ cat: c === "all" ? null : c })}
          >
            {c === "all" ? "すべて" : categoryLabel(c)}
          </button>
        ))}
        <span className="section-sub" style={{ marginLeft: "auto" }}>
          {filtered.length}カード
        </span>
      </div>

      {tiles.length === 0 ? (
        <div className="empty-note">表示できる相場データがありません</div>
      ) : (
        <div className="treemap-wrap" ref={wrapRef}>
          <svg viewBox={`0 0 ${VBW} ${VBH}`} role="img" aria-label="市場マップ(面積=流通規模、色=利益率)">
            <defs>
              {/* 案件なしタイル用の斜線テクスチャ(45°、トーンオントーン) */}
              <pattern id="tm-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="8" stroke={theme === "dark" ? "#4a4a46" : "#d8d6cf"} strokeWidth="2" />
              </pattern>
            </defs>
            {tiles.map((t) => {
              const n = t.item;
              const fill = n.deal ? divergingColor(n.rate, poles) : poles.neutral;
              const ink = inkFor(fill);
              const big = t.w > 118 && t.h > 52;
              return (
                <g
                  key={n.card_id}
                  className="tm-tile"
                  tabIndex={0}
                  role="button"
                  aria-label={`${n.name} ${n.deal ? `利益率${fmtPct(n.rate)}` : "案件なし"}`}
                  onClick={() => onOpenCard(n.card_id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onOpenCard(n.card_id);
                    }
                  }}
                  onPointerMove={(e) => showTip(e, n)}
                  onPointerLeave={() => setTip(null)}
                >
                  <rect
                    className="tm-fill"
                    x={t.x + 1}
                    y={t.y + 1}
                    width={Math.max(0.5, t.w - 2)}
                    height={Math.max(0.5, t.h - 2)}
                    rx="3"
                    fill={fill}
                  />
                  {!n.deal && (
                    <rect
                      x={t.x + 1}
                      y={t.y + 1}
                      width={Math.max(0.5, t.w - 2)}
                      height={Math.max(0.5, t.h - 2)}
                      rx="3"
                      fill="url(#tm-hatch)"
                      pointerEvents="none"
                    />
                  )}
                  {big && (
                    // 入れ子svgでタイル外へのラベルはみ出しをクリップする
                    <svg
                      x={t.x + 1}
                      y={t.y + 1}
                      width={Math.max(0.5, t.w - 2)}
                      height={Math.max(0.5, t.h - 2)}
                      pointerEvents="none"
                      style={{ overflow: "hidden" }}
                    >
                      <text x={9} y={21} fontSize="13" fontWeight="600" fill={ink}>
                        {truncateToWidth(n.name, t.w - 22, 13)}
                      </text>
                      <text x={9} y={39} fontSize="12" fill={ink} opacity="0.85" style={{ fontVariantNumeric: "tabular-nums" }}>
                        {n.deal ? fmtSignedPct(n.rate) : "案件なし"}
                      </text>
                    </svg>
                  )}
                </g>
              );
            })}
          </svg>
          {tip && (
            <div className="tm-tooltip" style={{ left: tip.x, top: tip.y }}>
              <b>{tip.node.name}</b>
              <br />
              <span className="text2">相場</span> <b>{fmtUsd(tip.node.median)}</b> ×{" "}
              <b>{tip.node.count30}件/30日</b>
              <br />
              {tip.node.deal ? (
                <>
                  <span className="text2">最良案件 利益率</span>{" "}
                  <b className={tip.node.rate >= 0 ? "pos" : "neg"}>{fmtSignedPct(tip.node.rate)}</b>
                  <br />
                  <span className="text2">スコア</span> <b>{opportunityScore(tip.node.deal)}</b>
                  <span className="muted">(クリックで詳細)</span>
                </>
              ) : (
                <span className="text2">アクティブな案件なし(履歴のみ)</span>
              )}
            </div>
          )}
        </div>
      )}

      <div className="tm-legend">
        <span className="scale">
          <span className="neg">▼ −50%</span>
          <svg width="140" height="10" aria-hidden="true">
            <defs>
              <linearGradient id="tm-scale" x1="0" y1="0" x2="1" y2="0">
                {stops.map((s, i) => (
                  <stop key={i} offset={s.off} stopColor={s.color} />
                ))}
              </linearGradient>
            </defs>
            <rect width="140" height="10" rx="3" fill="url(#tm-scale)" />
          </svg>
          <span className="pos">+50% ▲</span>
          <span className="muted">(利益率)</span>
        </span>
        <span className="hatch-key">
          <svg width="18" height="12" aria-hidden="true">
            <rect width="18" height="12" rx="2" fill={poles.neutral} />
            <line x1="2" y1="12" x2="14" y2="0" stroke={theme === "dark" ? "#4a4a46" : "#c8c6bf"} strokeWidth="2" />
          </svg>
          案件なし(履歴のみ)
        </span>
        <span>面積 = eBay中央値 × 30日販売数(月間流通規模)</span>
      </div>
    </div>
  );
}
