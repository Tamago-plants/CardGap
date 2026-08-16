// スプレッドバー: 想定売上を基準にした横積みバー(仕入原価 / 諸経費 / 利益)。
// 利益マイナス時はコストが売上を超えるので、超過分を赤セグメントで表す。
// セグメント間は 2px のサーフェスギャップ。ホバーで内訳数値ツールチップ。
import HoverTip from "./HoverTip.jsx";
import { fmtYen, fmtSignedYen } from "../lib/format.js";

export default function SpreadBar({ deal, width = 150 }) {
  const revenue = deal.revenue_jpy || 0;
  const cost = deal.buy_total_jpy || 0;
  const profit = deal.profit_jpy || 0;
  // 諸経費 = eBay手数料 + 発送送料。恒等式 売上 − 仕入 − 経費 = 利益 から逆算
  const fees = Math.max(0, revenue - cost - profit);
  if (revenue <= 0) {
    return <span className="muted">—</span>;
  }
  const total = Math.max(revenue, cost + fees);
  const s = 100 / total;
  let segs;
  if (profit >= 0) {
    segs = [
      { cls: "seg-cost", w: cost * s },
      { cls: "seg-fee", w: fees * s },
      { cls: "seg-profit", w: profit * s },
    ];
  } else {
    // 売上まではコスト+経費、それを超えた分(=赤字幅)を赤で示す
    const costShown = Math.min(cost, revenue);
    const feeShown = Math.max(0, revenue - costShown);
    segs = [
      { cls: "seg-cost", w: costShown * s },
      { cls: "seg-fee", w: feeShown * s },
      { cls: "seg-deficit", w: -profit * s },
    ];
  }
  const tip = (
    <>
      <span className="tip-row">
        <span>想定売上</span>
        <b>{fmtYen(revenue)}</b>
      </span>
      <span className="tip-row">
        <span>仕入総額</span>
        <b>{fmtYen(cost)}</b>
      </span>
      <span className="tip-row">
        <span>手数料+送料</span>
        <b>{fmtYen(fees)}</b>
      </span>
      <span className="tip-row">
        <span>実質利益</span>
        <b className={profit >= 0 ? "pos" : "neg"}>{fmtSignedYen(profit)}</b>
      </span>
    </>
  );
  return (
    <HoverTip tip={tip} width={190} style={{ display: "block", width }} ariaLabel="損益内訳バー">
      <span className="spread" aria-hidden="true">
        {segs
          .filter((g) => g.w > 0.5)
          .map((g, i) => (
            <span key={i} className={`spread-seg ${g.cls}`} style={{ width: `${g.w}%` }} />
          ))}
      </span>
    </HoverTip>
  );
}
