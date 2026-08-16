// 30日中央値のスパークライン(手書きSVG)。
// 上昇=正色 / 下降=負色の1本線。データ不足時は "—" を表示。
export default function Sparkline({ values, width = 110, height = 30 }) {
  if (!values || values.length < 2) {
    return (
      <span className="muted" style={{ fontSize: 11 }} aria-label="履歴データなし">
        —
      </span>
    );
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const step = (width - pad * 2) / (values.length - 1);
  const pts = values.map((v, i) => [
    pad + i * step,
    pad + (height - pad * 2) * (1 - (v - min) / span),
  ]);
  const d = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const up = values[values.length - 1] >= values[0];
  const color = up ? "var(--pos)" : "var(--neg)";
  const [ex, ey] = pts[pts.length - 1];
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
      style={{ display: "block" }}
    >
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
      {/* 終端ドット(サーフェス色リング付き) */}
      <circle cx={ex} cy={ey} r="3.4" fill="var(--surface)" />
      <circle cx={ex} cy={ey} r="2.2" fill={color} />
    </svg>
  );
}
