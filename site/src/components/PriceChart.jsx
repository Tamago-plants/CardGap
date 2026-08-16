// 価格推移チャート(手書きSVGの単系列ラインチャート)。
// 設計規約:
//   - 線は 2px(round join/cap)、系列色は #4269d0 の1色のみ
//   - データ点は r=4 の描画 + 半径12の透明ヒット領域(当たり判定 24px ≥ 8px)
//   - 単系列なので凡例なし。グリッドは薄い水平線のみ、軸テキストは控えめな色
//   - ホバーで縦クロスヘア + ツールチップ(日付・中央値$・件数)。キーボード
//     フォーカスでも同じ情報を出す
//   - y軸は0起点にせずデータ範囲+余白。軸ラベルに $ を明記
//   - データが2点未満なら「履歴がたまると表示されます」のプレースホルダ
import { useMemo, useRef, useState } from "react";
import { fmtDateShort, fmtUsd } from "../format.js";

// viewBox 座標系(レンダリングは width:100% で拡縮)
const VIEW_W = 640;
const VIEW_H = 260;
const MARGIN = { top: 12, right: 16, bottom: 28, left: 56 };

const SERIES_COLOR = "#4269d0";

/** min〜max を count 個程度の「切りのいい」目盛りに割る */
function niceTicks(min, max, count = 4) {
  const range = max - min;
  if (range <= 0) return [min];
  const rawStep = range / count;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const norm = rawStep / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) {
    ticks.push(Number(t.toFixed(6)));
  }
  return ticks;
}

export default function PriceChart({ points }) {
  const wrapRef = useRef(null);
  const [hoverIdx, setHoverIdx] = useState(null);

  // 座標計算(points が変わらない限り再計算しない)
  const geom = useMemo(() => {
    if (!points || points.length < 2) return null;

    const plotW = VIEW_W - MARGIN.left - MARGIN.right;
    const plotH = VIEW_H - MARGIN.top - MARGIN.bottom;

    // x: 日付を実時間軸で配置(欠測日があっても間隔が正しく出る)
    const times = points.map((p) => new Date(p.date + "T00:00:00Z").getTime());
    const tMin = Math.min(...times);
    const tMax = Math.max(...times);
    const tSpan = tMax - tMin || 1; // 同一日だけの場合のゼロ割ガード

    // y: データ範囲 + 上下8%の余白(0起点にしない)
    const values = points.map((p) => p.median_usd);
    let yMin = Math.min(...values);
    let yMax = Math.max(...values);
    if (yMax === yMin) {
      // 全点同値でも線が中央に描けるように上下に幅を持たせる
      const pad = Math.abs(yMin) * 0.1 || 1;
      yMin -= pad;
      yMax += pad;
    } else {
      const pad = (yMax - yMin) * 0.08;
      yMin -= pad;
      yMax += pad;
    }

    const xAt = (t) => MARGIN.left + ((t - tMin) / tSpan) * plotW;
    const yAt = (v) => MARGIN.top + (1 - (v - yMin) / (yMax - yMin)) * plotH;

    const coords = points.map((p, i) => ({
      x: xAt(times[i]),
      y: yAt(p.median_usd),
      point: p,
    }));

    const path = coords
      .map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(2)},${c.y.toFixed(2)}`)
      .join(" ");

    const yTicks = niceTicks(yMin, yMax, 4).map((v) => ({ v, y: yAt(v) }));

    // x軸ラベル: 最大6個を等間隔のインデックスで採用
    const labelCount = Math.min(6, points.length);
    const idxs = new Set();
    for (let i = 0; i < labelCount; i++) {
      idxs.add(Math.round((i * (points.length - 1)) / (labelCount - 1 || 1)));
    }
    const xTicks = [...idxs].map((i) => ({ x: coords[i].x, label: fmtDateShort(points[i].date) }));

    return { coords, path, yTicks, xTicks, plotH };
  }, [points]);

  if (!geom) {
    return <div className="chart-placeholder">履歴がたまると表示されます</div>;
  }

  const { coords, path, yTicks, xTicks } = geom;

  // ポインタ位置 → 最寄りのデータ点(クロスヘアはXにスナップする)
  const handleMove = (e) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return;
    const vx = ((e.clientX - rect.left) / rect.width) * VIEW_W;
    let best = 0;
    let bestDist = Infinity;
    coords.forEach((c, i) => {
      const d = Math.abs(c.x - vx);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    setHoverIdx(best);
  };

  const hover = hoverIdx != null ? coords[hoverIdx] : null;
  // ツールチップは右端40%で左側にフリップ
  const flip = hover && hover.x > VIEW_W * 0.6;

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label="eBay中央値の価格推移チャート"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* 水平グリッド(薄いヘアライン)と y軸ラベル($明記) */}
        {yTicks.map((t) => (
          <g key={t.v}>
            <line
              x1={MARGIN.left}
              x2={VIEW_W - MARGIN.right}
              y1={t.y}
              y2={t.y}
              stroke="var(--grid)"
              strokeWidth="1"
            />
            <text
              x={MARGIN.left - 8}
              y={t.y + 4}
              textAnchor="end"
              fontSize="11"
              fill="var(--text-muted)"
            >
              {fmtUsd(t.v, t.v >= 100 ? 0 : 1)}
            </text>
          </g>
        ))}

        {/* x軸ラベル(日付、控えめな色) */}
        {xTicks.map((t, i) => (
          <text
            key={i}
            x={t.x}
            y={VIEW_H - 8}
            textAnchor="middle"
            fontSize="11"
            fill="var(--text-muted)"
          >
            {t.label}
          </text>
        ))}

        {/* クロスヘア(ホバー中のみ) */}
        {hover && (
          <line
            x1={hover.x}
            x2={hover.x}
            y1={MARGIN.top}
            y2={VIEW_H - MARGIN.bottom}
            stroke="var(--text-muted)"
            strokeWidth="1"
          />
        )}

        {/* 系列ライン: 2px round */}
        <path
          d={path}
          fill="none"
          stroke={SERIES_COLOR}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* データ点: 白リング付き r=4。ホバー中の点は少し大きく */}
        {coords.map((c, i) => (
          <circle
            key={i}
            cx={c.x}
            cy={c.y}
            r={hoverIdx === i ? 5 : 4}
            fill={SERIES_COLOR}
            stroke="var(--surface)"
            strokeWidth="2"
          />
        ))}

        {/* 透明ヒット領域(半径12 = 直径24pxの当たり判定)。
            キーボードフォーカスでもツールチップを出す */}
        {coords.map((c, i) => (
          <circle
            key={`hit-${i}`}
            cx={c.x}
            cy={c.y}
            r="12"
            fill="transparent"
            tabIndex="0"
            aria-label={`${c.point.date} 中央値 ${fmtUsd(c.point.median_usd)} ${c.point.count}件`}
            style={{ outline: "none" }}
            onFocus={() => setHoverIdx(i)}
            onBlur={() => setHoverIdx(null)}
          />
        ))}
      </svg>

      {/* ツールチップ(値が主役、ラベルは従属) */}
      {hover && (
        <div
          className="chart-tooltip"
          style={{
            left: `${(hover.x / VIEW_W) * 100}%`,
            top: `${(hover.y / VIEW_H) * 100}%`,
            transform: flip
              ? "translate(calc(-100% - 12px), -50%)"
              : "translate(12px, -50%)",
          }}
        >
          <div className="tt-value">{fmtUsd(hover.point.median_usd)}</div>
          <div className="tt-label">
            {hover.point.date} / {hover.point.count}件
          </div>
        </div>
      )}
    </div>
  );
}
