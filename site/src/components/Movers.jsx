// 相場動向: 中央値の騰落(movers_up / movers_down)を左右2列で表示。
// 上昇=緑・下落=赤の色分けに加えて ▲/▼ の矢印記号を必ず併記する(色弱対応)。
import { fmtSignedPct, fmtUsd } from "../format.js";

function MoverList({ title, items, dir }) {
  return (
    <div className="movers-col">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="empty-note">該当なし</p>
      ) : (
        <ul>
          {items.map((m) => (
            <li key={`${m.card_id}-${m.date}`}>
              <span className="mover-name" title={m.display_name}>
                {m.display_name}
              </span>
              <span className="mover-price">
                {fmtUsd(m.prev_median_usd)} → {fmtUsd(m.median_usd)}
              </span>
              <span className={`mover-change ${dir}`}>
                {dir === "up" ? "▲" : "▼"} {fmtSignedPct(m.change_rate)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Movers({ summary }) {
  const up = summary?.movers_up || [];
  const down = summary?.movers_down || [];
  return (
    <section className="card">
      <h2>相場動向(eBay中央値の前回比)</h2>
      <div className="movers-grid">
        <MoverList title="📈 上昇" items={up} dir="up" />
        <MoverList title="📉 下落" items={down} dir="down" />
      </div>
    </section>
  );
}
