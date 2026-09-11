// ランキング: ボード切替チップ + TOP10 リスト + 仕入れプランナー。
// 急騰/急落は history から全カード分を再計算(サマリのTOP5より多く出せる)。
// メルカリ系ボード(売れ筋/急騰/急落)は summary.json のメルカリ売却相場から。
// データが空のボードはチップごと隠す(空シェルを見せない)。
import { useMemo, useState } from "react";
import CardThumb from "./CardThumb.jsx";
import ScoreBadge from "./ScoreBadge.jsx";
import Sparkline from "./Sparkline.jsx";
import {
  categoryLabel,
  confidenceLabel,
  fmtMarket,
  fmtPct,
  fmtSignedPct,
  fmtSignedYen,
  fmtUsd,
  fmtYen,
  reliabilityLabel,
  sourceLabel,
} from "../lib/format.js";
import { computeMovers, marketOf, medianSeries } from "../lib/data.js";
import { opportunityScore } from "../lib/score.js";

const BOARDS = [
  { id: "score", label: "総合スコア" },
  { id: "rate", label: "利益率" },
  { id: "profit", label: "利益額" },
  { id: "up", label: "急騰" },
  { id: "down", label: "急落" },
  { id: "liquidity", label: "流動性" },
  { id: "msell", label: "メルカリ売れ筋" },
  { id: "mup", label: "メルカリ急騰" },
  { id: "mdown", label: "メルカリ急落" },
];

/** 予算内スコア順グリーディ(各出品1枚) */
function planPurchases(deals, budget) {
  const sorted = deals
    .filter((d) => opportunityScore(d) > 0 && (d.buy_total_jpy || 0) > 0)
    .sort((a, b) => opportunityScore(b) - opportunityScore(a));
  const picked = [];
  let remain = budget;
  for (const d of sorted) {
    if (d.buy_total_jpy <= remain) {
      picked.push(d);
      remain -= d.buy_total_jpy;
    }
  }
  const totalBuy = picked.reduce((a, d) => a + d.buy_total_jpy, 0);
  const totalProfit = picked.reduce((a, d) => a + d.profit_jpy, 0);
  return { picked, totalBuy, totalProfit, avgRate: totalBuy > 0 ? totalProfit / totalBuy : 0 };
}

function Planner({ deals, onOpenDeal }) {
  const [budget, setBudget] = useState(50000);
  const plan = useMemo(() => planPurchases(deals, budget || 0), [deals, budget]);
  return (
    <div className="card planner">
      <h3>仕入れプランナー</h3>
      <p className="section-sub" style={{ margin: 0 }}>
        予算内でスコア順に仕入れセットを提案(各出品1枚)
      </p>
      <div className="planner-input">
        <span style={{ alignSelf: "center", color: "var(--text2)", fontWeight: 600 }}>予算 ¥</span>
        <input
          type="number"
          min="0"
          step="1000"
          value={budget}
          onChange={(e) => setBudget(Number(e.target.value))}
          aria-label="予算(円)"
        />
        {[30000, 50000, 100000].map((b) => (
          <button key={b} type="button" className="btn btn-sm" onClick={() => setBudget(b)}>
            {b / 10000}万
          </button>
        ))}
      </div>
      {plan.picked.length === 0 ? (
        <div className="empty-note" style={{ padding: "16px 0" }}>
          予算内で買える利益プラスの案件がありません
        </div>
      ) : (
        <>
          <div className="planner-summary">
            <div className="ps">
              <div className="ps-label">合計仕入</div>
              <div className="ps-value">{fmtYen(plan.totalBuy)}</div>
            </div>
            <div className="ps">
              <div className="ps-label">想定合計利益</div>
              <div className={`ps-value ${plan.totalProfit >= 0 ? "pos" : "neg"}`}>
                {fmtSignedYen(plan.totalProfit)}
              </div>
            </div>
            <div className="ps">
              <div className="ps-label">平均利益率</div>
              <div className="ps-value">{fmtPct(plan.avgRate)}</div>
            </div>
          </div>
          {plan.picked.map((d, i) => (
            <button key={i} type="button" className="planner-row" onClick={() => onOpenDeal(d)}>
              <span className="chip">{sourceLabel(d.source)}</span>
              <span className="pr-name">{d.display_name}</span>
              <span className="num" style={{ color: "var(--text2)" }}>
                {fmtYen(d.buy_total_jpy)}
              </span>
              <span className={`num ${d.profit_jpy >= 0 ? "pos" : "neg"}`} style={{ fontWeight: 700 }}>
                {fmtSignedYen(d.profit_jpy)}
              </span>
            </button>
          ))}
        </>
      )}
      <p className="planner-note">同時に複数枚を売る場合は発送・手数料が変わる場合があります。</p>
    </div>
  );
}

export default function Rankings({ deals, history, summary, params, setParams, onOpenDeal, onOpenCard }) {
  const histMap = useMemo(() => {
    const m = new Map();
    for (const c of (history && history.cards) || []) m.set(c.card_id, c);
    return m;
  }, [history]);

  const ebayMovers = useMemo(() => computeMovers(history), [history]);
  const mUp = (summary && summary.mercari_movers_up) || [];
  const mDown = (summary && summary.mercari_movers_down) || [];
  const mSell = (summary && summary.mercari_top_selling) || [];

  // データが空のボードはチップを出さない(空シェル防止)
  const visibleBoards = useMemo(() => {
    const avail = {
      score: deals.length > 0,
      rate: deals.length > 0,
      profit: deals.length > 0,
      liquidity: deals.length > 0,
      up: ebayMovers.some((m) => m.change_rate > 0),
      down: ebayMovers.some((m) => m.change_rate < 0),
      msell: mSell.length > 0,
      mup: mUp.length > 0,
      mdown: mDown.length > 0,
    };
    const vis = BOARDS.filter((b) => avail[b.id]);
    return vis.length > 0 ? vis : BOARDS.slice(0, 1); // 全滅時は総合スコアだけ出して空メッセージに任せる
  }, [deals, ebayMovers, mUp, mDown, mSell]);

  const board = visibleBoards.some((b) => b.id === params.board) ? params.board : visibleBoards[0].id;

  const rows = useMemo(() => {
    // カード単位ボード(騰落・売れ筋)は表示値を組み立てて共通シェイプで返す
    if (board === "up" || board === "down") {
      const filtered =
        board === "up"
          ? ebayMovers.filter((m) => m.change_rate > 0).sort((a, b) => b.change_rate - a.change_rate)
          : ebayMovers.filter((m) => m.change_rate < 0).sort((a, b) => a.change_rate - b.change_rate);
      return filtered.slice(0, 10).map((m) => ({
        kind: "card",
        cardId: m.card_id,
        name: m.display_name,
        category: m.category,
        sub: `相場ウォッチ(${m.date})`,
        value: (
          <span className={m.change_rate >= 0 ? "pos" : "neg"}>
            {m.change_rate >= 0 ? "▲" : "▼"}
            {fmtSignedPct(m.change_rate)}
          </span>
        ),
        valueSub: `${fmtUsd(m.prev_median_usd)} → ${fmtUsd(m.median_usd)} / ${m.count}件`,
      }));
    }
    if (board === "mup" || board === "mdown") {
      const list = board === "mup" ? mUp : mDown;
      return list.slice(0, 10).map((m) => ({
        kind: "card",
        cardId: m.card_id,
        name: m.display_name,
        category: m.category,
        sub: `メルカリ売却相場(${m.date})`,
        value: (
          <span className={m.change_rate >= 0 ? "pos" : "neg"}>
            {m.change_rate >= 0 ? "▲" : "▼"}
            {fmtSignedPct(m.change_rate)}
          </span>
        ),
        valueSub: `${fmtYen(m.prev_median_jpy)} → ${fmtYen(m.median_jpy)} / ${m.count}件`,
      }));
    }
    if (board === "msell") {
      return mSell.slice(0, 10).map((m) => ({
        kind: "card",
        cardId: m.card_id,
        name: m.display_name,
        category: m.category,
        sub: `メルカリ売却相場(${m.date})`,
        value: <span>{m.count}件/30日</span>,
        valueSub: `中央値 ${fmtYen(m.median_jpy)}`,
      }));
    }
    const keyed = deals.map((d) => ({ kind: "deal", deal: d, score: opportunityScore(d) }));
    const sorters = {
      score: (a, b) => b.score - a.score,
      rate: (a, b) => (b.deal.profit_rate || -9) - (a.deal.profit_rate || -9),
      profit: (a, b) => (b.deal.profit_jpy || -9e9) - (a.deal.profit_jpy || -9e9),
      liquidity: (a, b) => marketOf(b.deal).count - marketOf(a.deal).count,
    };
    return keyed.sort(sorters[board] || sorters.score).slice(0, 10);
  }, [board, deals, ebayMovers, mUp, mDown, mSell]);

  const mainValue = (row) => {
    if (row.kind === "card") return { value: row.value, sub: row.valueSub };
    const d = row.deal;
    const mk = marketOf(d);
    switch (board) {
      case "rate":
        return {
          value: <span className={d.profit_rate >= 0 ? "pos" : "neg"}>{fmtSignedPct(d.profit_rate)}</span>,
          sub: `利益 ${fmtSignedYen(d.profit_jpy)}`,
        };
      case "profit":
        return {
          value: <span className={d.profit_jpy >= 0 ? "pos" : "neg"}>{fmtSignedYen(d.profit_jpy)}</span>,
          sub: `利益率 ${fmtSignedPct(d.profit_rate)}`,
        };
      case "liquidity":
        return {
          value: <span>{mk.count}件/30日</span>,
          sub: `中央値 ${fmtMarket(mk.median, mk.currency)}`,
        };
      default:
        return {
          value: <span>{row.score}</span>,
          sub: `${fmtSignedYen(d.profit_jpy)} / ${fmtSignedPct(d.profit_rate)}`,
        };
    }
  };

  return (
    <>
      <div className="board-chips" role="group" aria-label="ランキングボード切替">
        {visibleBoards.map((b) => (
          <button
            key={b.id}
            type="button"
            className={`filter-chip${board === b.id ? " active" : ""}`}
            onClick={() => setParams({ board: b.id === "score" ? null : b.id })}
          >
            {b.label}
          </button>
        ))}
      </div>
      <div className="rankings-grid">
        <div className="card rank-list">
          {rows.length === 0 ? (
            <div className="empty-note">このボードに表示できるデータがありません</div>
          ) : (
            rows.map((row, i) => {
              const isDeal = row.kind === "deal";
              const d = isDeal ? row.deal : null;
              const cardId = isDeal ? d.card_id : row.cardId;
              const name = isDeal ? d.display_name : row.name;
              const hist = histMap.get(cardId);
              const spark = medianSeries(hist, 30);
              const mv = mainValue(row);
              const mk = isDeal ? marketOf(d) : null;
              return (
                <button
                  key={`${cardId}-${i}`}
                  type="button"
                  className="rank-row"
                  onClick={() => (isDeal ? onOpenDeal(d) : onOpenCard(cardId))}
                >
                  <span className="rank-pos">
                    {i < 3 ? <span className={`medal m${i + 1}`}>{i + 1}</span> : i + 1}
                  </span>
                  <CardThumb src={isDeal ? d.image_url : null} name={name} />
                  <span className="rank-name">
                    <span className="r-title">{name}</span>
                    <span className="r-sub">
                      {isDeal
                        ? `${sourceLabel(d.source)} ${fmtYen(d.buy_price_jpy)} → ${fmtMarket(mk.median, mk.currency)}`
                        : row.sub}
                    </span>
                  </span>
                  <span className="rank-spark" aria-hidden="true">
                    <Sparkline values={spark} />
                  </span>
                  <span className="rank-main">
                    <span className="r-value">{mv.value}</span>
                    <br />
                    <span className="r-vsub">{mv.sub}</span>
                  </span>
                  <span className="rank-chips">
                    {isDeal ? (
                      <>
                        <span className={`chip c-${d.confidence}`}>{confidenceLabel(d.confidence)}</span>
                        <span className={`chip ${d.reliability === "ok" ? "" : "c-low"}`}>
                          {reliabilityLabel(d.reliability)}
                        </span>
                      </>
                    ) : (
                      <span className="chip">{categoryLabel(row.category)}</span>
                    )}
                  </span>
                </button>
              );
            })
          )}
        </div>
        <Planner deals={deals} onOpenDeal={onOpenDeal} />
      </div>
    </>
  );
}
