// 価格チャート(手書きSVG)。中央値ライン2px + min〜max帯(落札レンジ)を上段、
// 日次販売数のミニバーを別チャートとして下段に描く(2軸チャートは使わない)。
// クロスヘア + ツールチップは上段のポインタ操作で両方の値を表示する。
import { useMemo, useRef, useState } from "react";
import { fmtDateShort, fmtUsd } from "../lib/format.js";

const VBW = 560; // viewBox幅(表示はCSSで100%スケール)
const MAIN_H = 190;
const BAR_H = 56;
const PAD = { l: 46, r: 12, t: 10, b: 20 };

/** 切りのいい目盛り値を作る */
function niceTicks(min, max, n = 4) {
  if (!(max > min)) return [min];
  const span = max - min;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || mag * 10;
  const start = Math.ceil(min / step) * step;
  const out = [];
  for (let v = start; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

export default function PriceChart({ points }) {
  const wrapRef = useRef(null);
  const [hover, setHover] = useState(null); // {i, px, py}

  const model = useMemo(() => {
    if (!points || points.length < 2) return null;
    const w = VBW - PAD.l - PAD.r;
    const h = MAIN_H - PAD.t - PAD.b;
    const lo = Math.min(...points.map((p) => p.min_usd ?? p.median_usd));
    const hi = Math.max(...points.map((p) => p.max_usd ?? p.median_usd));
    const span = hi - lo || 1;
    const yLo = lo - span * 0.06;
    const yHi = hi + span * 0.06;
    const x = (i) => PAD.l + (w * i) / (points.length - 1);
    const y = (v) => PAD.t + h * (1 - (v - yLo) / (yHi - yLo));
    const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.median_usd).toFixed(1)}`).join("");
    const bandTop = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.max_usd ?? p.median_usd).toFixed(1)}`).join("");
    const bandBottom = points
      .slice()
      .reverse()
      .map((p, ri) => {
        const i = points.length - 1 - ri;
        return `L${x(i).toFixed(1)},${y(p.min_usd ?? p.median_usd).toFixed(1)}`;
      })
      .join("");
    const yTicks = niceTicks(yLo, yHi, 4);
    // X軸目盛りは5個程度に間引く
    const tickEvery = Math.max(1, Math.round(points.length / 5));
    const xTicks = points.map((p, i) => ({ i, label: fmtDateShort(p.date) })).filter((t) => t.i % tickEvery === 0);
    const maxCount = Math.max(1, ...points.map((p) => p.count || 0));
    return { x, y, line, band: bandTop + bandBottom + "Z", yTicks, xTicks, maxCount, yLo, yHi };
  }, [points]);

  if (!model) {
    return <div className="chart-placeholder">価格履歴が2日分未満のためチャートを表示できません</div>;
  }

  const { x, y, line, band, yTicks, xTicks, maxCount } = model;
  const n = points.length;

  const onMove = (e) => {
    const rect = wrapRef.current.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * VBW;
    const t = (vx - PAD.l) / (VBW - PAD.l - PAD.r);
    const i = Math.max(0, Math.min(n - 1, Math.round(t * (n - 1))));
    setHover({ i, leftPct: (x(i) / VBW) * 100 });
  };

  const hp = hover ? points[hover.i] : null;
  const barW = Math.min(12, ((VBW - PAD.l - PAD.r) / n) * 0.62);

  return (
    <div className="chart-block" ref={wrapRef} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      <div className="chart-legend">
        <span className="lk">
          <span className="lk-line" aria-hidden="true" />
          中央値
        </span>
        <span className="lk">
          <span className="lk-band" aria-hidden="true" />
          落札レンジ(min〜max)
        </span>
      </div>
      <svg viewBox={`0 0 ${VBW} ${MAIN_H}`} role="img" aria-label="eBay落札価格の推移チャート">
        {/* グリッド + Y目盛 */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={VBW - PAD.r} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth="1" />
            <text x={PAD.l - 6} y={y(v) + 3.5} textAnchor="end" fontSize="10" fill="var(--muted)" style={{ fontVariantNumeric: "tabular-nums" }}>
              ${v >= 100 ? Math.round(v) : v}
            </text>
          </g>
        ))}
        {/* X目盛 */}
        {xTicks.map((t) => (
          <text key={t.i} x={x(t.i)} y={MAIN_H - 5} textAnchor="middle" fontSize="10" fill="var(--muted)">
            {t.label}
          </text>
        ))}
        {/* レンジ帯(同一系列色の10%ウォッシュ) */}
        <path d={band} fill="var(--accent)" opacity="0.13" />
        {/* 中央値ライン */}
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {/* クロスヘア */}
        {hover && (
          <g>
            <line x1={x(hover.i)} x2={x(hover.i)} y1={PAD.t} y2={MAIN_H - PAD.b} stroke="var(--chart-axis)" strokeWidth="1" />
            <circle cx={x(hover.i)} cy={y(points[hover.i].median_usd)} r="4.5" fill="var(--surface)" />
            <circle cx={x(hover.i)} cy={y(points[hover.i].median_usd)} r="3" fill="var(--accent)" />
          </g>
        )}
        {/* ベースライン */}
        <line x1={PAD.l} x2={VBW - PAD.r} y1={MAIN_H - PAD.b} y2={MAIN_H - PAD.b} stroke="var(--chart-axis)" strokeWidth="1" />
      </svg>

      <div className="mini-title">日次販売数(件)</div>
      <svg viewBox={`0 0 ${VBW} ${BAR_H}`} role="img" aria-label="日次販売数のミニバーチャート">
        {points.map((p, i) => {
          const bh = ((BAR_H - 14) * (p.count || 0)) / maxCount;
          return (
            <rect
              key={i}
              x={x(i) - barW / 2}
              y={BAR_H - 2 - bh}
              width={barW}
              height={Math.max(bh, p.count ? 1.5 : 0)}
              rx="1.5"
              fill="var(--accent)"
              opacity={hover && hover.i === i ? 0.95 : 0.5}
            />
          );
        })}
        <line x1={PAD.l} x2={VBW - PAD.r} y1={BAR_H - 2} y2={BAR_H - 2} stroke="var(--chart-axis)" strokeWidth="1" />
        {/* 最大値の目安ラベル */}
        <text x={PAD.l - 6} y={12} textAnchor="end" fontSize="9.5" fill="var(--muted)" style={{ fontVariantNumeric: "tabular-nums" }}>
          {maxCount}
        </text>
      </svg>

      {hover && hp && (
        <div
          className="chart-tooltip"
          style={{
            left: `min(max(${hover.leftPct}%, 90px), calc(100% - 110px))`,
            top: 26,
            transform: "translateX(-50%)",
          }}
        >
          <span className="text2">{hp.date}</span>
          <br />
          中央値 <b>{fmtUsd(hp.median_usd)}</b>
          <br />
          レンジ <b>{fmtUsd(hp.min_usd)}〜{fmtUsd(hp.max_usd)}</b>
          <br />
          販売数 <b>{hp.count}件</b>
        </div>
      )}
    </div>
  );
}
