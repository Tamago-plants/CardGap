// Opportunity Score バッジ。ホバー/フォーカスで計算内訳ツールチップを出す。
import HoverTip from "./HoverTip.jsx";
import { scoreParts, scoreTier } from "../lib/score.js";

export default function ScoreBadge({ deal }) {
  const p = scoreParts(deal);
  const tier = scoreTier(p.score);
  const tip = p.negative ? (
    <>利益がマイナスのためスコアは 0 です。</>
  ) : (
    <>
      <span className="tip-row">
        <span>利益率係数</span>
        <b>{p.rateF.toFixed(2)}</b>
      </span>
      <span className="tip-row">
        <span>流動性係数</span>
        <b>{p.liqF.toFixed(2)}</b>
      </span>
      <span className="tip-row">
        <span>確度重み</span>
        <b>{p.confW.toFixed(2)}</b>
      </span>
      <span className="tip-row">
        <span>信頼度重み</span>
        <b>{p.relW.toFixed(2)}</b>
      </span>
      <span className="tip-row" style={{ marginTop: 4 }}>
        <span>= 100 × 積</span>
        <b>{p.score}</b>
      </span>
    </>
  );
  return (
    <HoverTip tip={tip} width={200} ariaLabel={`スコア ${p.score}(内訳あり)`}>
      <span className={`score-badge tier-${tier}`}>{p.score}</span>
    </HoverTip>
  );
}
