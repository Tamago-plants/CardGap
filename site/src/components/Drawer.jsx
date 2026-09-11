// 詳細ドロワー(右スライドオーバー、モバイルは全画面)。
// どの画面からもカード/案件クリックで開く。ESC・オーバーレイクリックで閉じる。
// 損益ブレークダウン / What-ifシミュレータ / 価格チャート / スナップショット表 /
// 他の仕入れ候補 を1枚に集約する、このツールの核体験。
// 相場は market_source(eBay=USD / メルカリ=JPY)に合わせて表記・リンク・
// シミュレータのモデルを切り替える。
import { useEffect, useMemo, useRef, useState } from "react";
import CardThumb from "./CardThumb.jsx";
import ScoreBadge from "./ScoreBadge.jsx";
import PriceChart from "./PriceChart.jsx";
import {
  categoryLabel,
  confidenceLabel,
  fmtMarket,
  fmtPct,
  fmtSignedPct,
  fmtSignedYen,
  fmtUsd,
  fmtYen,
  marketLabel,
  reliabilityLabel,
  sourceLabel,
} from "../lib/format.js";
import { dealKey, ebaySoldUrl, isNewDeal, marketOf, mercariSoldUrl } from "../lib/data.js";
import {
  breakevenBuy,
  breakevenBuyMercari,
  computeMercariProfit,
  computeProfit,
  mercariSellParams,
} from "../lib/profit.js";

/** 損益ブレークダウン(横バー + 数値は必ずテキスト併記) */
function PlBreakdown({ deal, marketSource }) {
  const revenue = deal.revenue_jpy || 0;
  const fees = deal.ebay_fees_jpy || 0;
  const cost = deal.buy_total_jpy || 0;
  const profit = deal.profit_jpy || 0;
  const ship = Math.max(0, revenue - fees - cost - profit);
  const max = Math.max(revenue, 1);
  const feeLabel = marketSource === "mercari" ? "販売手数料" : "eBay手数料";
  const rows = [
    { label: "想定売上", v: revenue, cls: "seg-cost", signed: false },
    { label: feeLabel, v: -fees, cls: "seg-fee", signed: true },
    { label: "発送送料", v: -ship, cls: "seg-fee", signed: true },
    { label: "仕入総額", v: -cost, cls: "seg-fee", signed: true },
    { label: "実質利益", v: profit, cls: profit >= 0 ? "seg-profit" : "seg-deficit", signed: true },
  ];
  return (
    <table className="pl-table">
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <td className="pl-label">{r.label}</td>
            <td>
              <div
                className={`pl-bar ${r.cls}`}
                style={{ width: `${Math.max(1.5, (Math.abs(r.v) / max) * 100)}%` }}
                aria-hidden="true"
              />
            </td>
            <td className={`pl-num ${r.label === "実質利益" ? (r.v >= 0 ? "pos" : "neg") : ""}`}>
              {r.signed ? fmtSignedYen(r.v) : fmtYen(r.v)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** What-if シミュレータ(profit.py と同一式をJSで再現、ライブ計算)。
 *  mode="ebay" は USD 売値 + 為替、mode="mercari" は円の想定売値のみ(為替は関与しない)。 */
function WhatIf({ mode, initialBuy, initialSell, fx, model, source }) {
  const [buy, setBuy] = useState(initialBuy);
  const [sell, setSell] = useState(initialSell);
  useEffect(() => {
    setBuy(initialBuy);
    setSell(initialSell);
  }, [initialBuy, initialSell, mode]);

  const isMercari = mode === "mercari";
  const res = useMemo(
    () =>
      isMercari
        ? computeMercariProfit({ sellJpy: Number(sell) || 0, buyJpy: Number(buy) || 0, model, source })
        : computeProfit({ usd: Number(sell) || 0, buyJpy: Number(buy) || 0, fx, model, source }),
    [sell, buy, fx, model, source, isMercari]
  );
  const be = useMemo(
    () =>
      isMercari
        ? breakevenBuyMercari({ sellJpy: Number(sell) || 0, model, source })
        : breakevenBuy({ usd: Number(sell) || 0, fx, model, source }),
    [sell, fx, model, source, isMercari]
  );

  const buyMax = Math.max(Math.ceil((Math.max(initialBuy, be) * 1.6) / 1000) * 1000, 5000);
  const sellMax = isMercari
    ? Math.max(Math.ceil((initialSell * 1.6) / 1000) * 1000, 5000)
    : Math.max(Math.ceil((initialSell * 1.6) / 10) * 10, 20);
  const sellStep = isMercari ? 100 : 1;

  return (
    <div className="whatif">
      <div className="wi-field">
        <label htmlFor="wi-buy">
          <span>仕入価格(円)</span>
          <span className="num">{fmtYen(buy)}</span>
        </label>
        <div className="wi-inputs">
          <input
            id="wi-buy"
            type="number"
            min="0"
            step="100"
            value={buy}
            onChange={(e) => setBuy(Number(e.target.value))}
          />
          <input
            type="range"
            min="0"
            max={buyMax}
            step="100"
            value={Math.min(buy, buyMax)}
            onChange={(e) => setBuy(Number(e.target.value))}
            aria-label="仕入価格スライダー"
          />
        </div>
      </div>
      <div className="wi-field">
        <label htmlFor="wi-sell">
          <span>{isMercari ? "想定売値(円)" : "売却額(USD)"}</span>
          <span className="num">{isMercari ? fmtYen(sell) : fmtUsd(sell)}</span>
        </label>
        <div className="wi-inputs">
          <input
            id="wi-sell"
            type="number"
            min="0"
            step={sellStep}
            value={sell}
            onChange={(e) => setSell(Number(e.target.value))}
          />
          <input
            type="range"
            min="0"
            max={sellMax}
            step={sellStep}
            value={Math.min(sell, sellMax)}
            onChange={(e) => setSell(Number(e.target.value))}
            aria-label={isMercari ? "想定売値スライダー" : "売却額スライダー"}
          />
        </div>
      </div>
      <div className="wi-results">
        <div className="wr">
          <div className="wr-label">実質利益</div>
          <div className={`wr-value ${res.profit >= 0 ? "pos" : "neg"}`}>{fmtSignedYen(res.profit)}</div>
        </div>
        <div className="wr">
          <div className="wr-label">利益率</div>
          <div className={`wr-value ${res.rate >= 0 ? "pos" : "neg"}`}>{fmtSignedPct(res.rate)}</div>
        </div>
        <div className="wr">
          <div className="wr-label">損益分岐の仕入上限</div>
          <div className="wr-value">{fmtYen(be)}</div>
        </div>
      </div>
      <button
        type="button"
        className="btn btn-sm wi-reset"
        onClick={() => {
          setBuy(initialBuy);
          setSell(initialSell);
        }}
      >
        初期値に戻す
      </button>
    </div>
  );
}

export default function Drawer({
  card, // カード情報(deal が無くても表示できる形)
  deal, // アクティブな案件(null 可)
  cardDeals, // 同一カードの全案件
  histCard, // history.json のカードエントリ(null 可)
  summary,
  onClose,
  onSelectDeal,
}) {
  const panelRef = useRef(null);
  const [range, setRange] = useState(90);
  const [seriesChoice, setSeriesChoice] = useState(null); // null = 自動(新しい方)

  // ESC で閉じる + 簡易フォーカストラップ + 背景スクロールロック
  useEffect(() => {
    const prevFocus = document.activeElement;
    const panel = panelRef.current;
    const closeBtn = panel && panel.querySelector(".drawer-close");
    if (closeBtn) closeBtn.focus();
    document.body.style.overflow = "hidden";
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      } else if (e.key === "Tab" && panel) {
        const focusables = panel.querySelectorAll(
          'button, a[href], input, select, [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      if (prevFocus && prevFocus.focus) prevFocus.focus();
    };
  }, [onClose, card && card.card_id]);

  // カードが変わったらチャート系列の手動選択をリセット
  useEffect(() => {
    setSeriesChoice(null);
  }, [card && card.card_id]);

  const model = summary && summary.profit_model;
  const fx = (deal && deal.fx_rate) || (summary && summary.fx_rate) || 150;
  const generatedAt = summary && summary.generated_at;
  const mk = deal ? marketOf(deal) : null;

  const ebayPts = (histCard && histCard.points) || [];
  const mercPts = (histCard && histCard.mercari_points) || [];

  // チャート初期系列: 両方あれば新しい日付の方、片方だけならその系列
  const autoSeries = useMemo(() => {
    if (ebayPts.length === 0 && mercPts.length > 0) return "mercari";
    if (mercPts.length === 0) return "ebay";
    const lastEbay = ebayPts[ebayPts.length - 1].date || "";
    const lastMerc = mercPts[mercPts.length - 1].date || "";
    return lastMerc > lastEbay ? "mercari" : "ebay";
  }, [histCard]);
  const series = seriesChoice || autoSeries;
  const chartCurrency = series === "mercari" ? "JPY" : "USD";

  // PriceChart 用に {date, median, min, max, count} へ正規化
  const chartPoints = useMemo(() => {
    const src = series === "mercari" ? mercPts : ebayPts;
    return src.slice(-range).map((p) =>
      series === "mercari"
        ? { date: p.date, median: p.median_jpy, min: p.min_jpy, max: p.max_jpy, count: p.count }
        : { date: p.date, median: p.median_usd, min: p.min_usd, max: p.max_usd, count: p.count }
    );
  }, [histCard, series, range]);

  const snaps = useMemo(() => {
    const src = series === "mercari" ? mercPts : ebayPts;
    return src
      .slice(-10)
      .reverse()
      .map((p) =>
        series === "mercari"
          ? { date: p.date, median: p.median_jpy, min: p.min_jpy, max: p.max_jpy, count: p.count }
          : { date: p.date, median: p.median_usd, min: p.min_usd, max: p.max_usd, count: p.count }
      );
  }, [histCard, series]);

  // What-if のモード: 案件があればその相場ソース、なければ履歴のある方
  const whatifMode = deal ? mk.source : autoSeries;
  const whatifSource = (deal && deal.source) || "mercari";
  const latestSell = deal
    ? mk.median ?? 0
    : whatifMode === "mercari"
      ? (mercPts.length > 0 ? mercPts[mercPts.length - 1].median_jpy : 0)
      : (ebayPts.length > 0 ? ebayPts[ebayPts.length - 1].median_usd : 0);
  const initialBuy = deal
    ? deal.buy_price_jpy
    : whatifMode === "mercari"
      ? breakevenBuyMercari({ sellJpy: latestSell, model, source: whatifSource })
      : breakevenBuy({ usd: latestSell, fx, model, source: whatifSource });
  const mercariSell = mercariSellParams(model);

  // 売り切れ検索リンク: メルカリ相場ならメルカリSold、それ以外は eBay Sold
  const soldSource = deal ? mk.source : (ebayPts.length === 0 && mercPts.length > 0 ? "mercari" : "ebay");

  const others = (cardDeals || []).filter((d) => !deal || dealKey(d) !== dealKey(deal));
  const isNew = deal && isNewDeal(deal, generatedAt);

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />
      <aside
        className="drawer"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${card.display_name} の詳細`}
      >
        <div className="drawer-head">
          <CardThumb src={deal && deal.image_url} name={card.display_name} size="xl" />
          <div className="dh-body">
            <h2>{card.display_name}</h2>
            <div className="drawer-chips">
              <span className="chip">{categoryLabel(card.category)}</span>
              {card.psa_grade ? <span className="chip c-psa">PSA{Math.round(card.psa_grade)}</span> : null}
              {isNew ? <span className="chip c-new">NEW</span> : null}
              {deal ? <span className="chip">{sourceLabel(deal.source)}</span> : null}
              {deal ? (
                <span className={`chip c-${deal.confidence}`}>{confidenceLabel(deal.confidence)}</span>
              ) : null}
              {deal ? (
                <span className={`chip ${deal.reliability === "ok" ? "" : "c-low"}`}>
                  {reliabilityLabel(deal.reliability)}
                </span>
              ) : null}
            </div>
            {deal && deal.title ? (
              <div className="muted" style={{ fontSize: 11, marginTop: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {deal.title}
              </div>
            ) : null}
            <div className="drawer-actions">
              {deal && deal.listing_url ? (
                <a className="btn btn-primary btn-sm" href={deal.listing_url} target="_blank" rel="noopener noreferrer">
                  出品を開く ↗
                </a>
              ) : null}
              {soldSource === "mercari" ? (
                <a className="btn btn-sm" href={mercariSoldUrl(card)} target="_blank" rel="noopener noreferrer">
                  メルカリSoldを確認 ↗
                </a>
              ) : (
                <a className="btn btn-sm" href={ebaySoldUrl(card)} target="_blank" rel="noopener noreferrer">
                  eBay Soldを確認 ↗
                </a>
              )}
            </div>
          </div>
          <button type="button" className="icon-btn drawer-close" onClick={onClose} aria-label="閉じる">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="drawer-body">
          {deal ? (
            <>
              <div className="d-summary">
                <div className="ds">
                  <div className="ds-label">仕入({sourceLabel(deal.source)})</div>
                  <div className="ds-value">{fmtYen(deal.buy_price_jpy)}</div>
                </div>
                <div className="ds">
                  <div className="ds-label">{marketLabel(mk.source)}(中央値)</div>
                  <div className="ds-value">
                    {fmtMarket(mk.median, mk.currency)}{" "}
                    <span className="muted" style={{ fontSize: 10.5, fontWeight: 500 }}>
                      {mk.count}件/30日
                    </span>
                  </div>
                </div>
                <div className="ds">
                  <div className="ds-label">実質利益 / 利益率</div>
                  <div className={`ds-value ${deal.profit_jpy >= 0 ? "pos" : "neg"}`}>
                    {fmtSignedYen(deal.profit_jpy)}
                    <span style={{ fontSize: 11.5, marginLeft: 4 }}>({fmtSignedPct(deal.profit_rate)})</span>
                  </div>
                </div>
              </div>

              <div className="drawer-section">
                <h3>
                  損益ブレークダウン{" "}
                  <span style={{ marginLeft: 6 }}>
                    <ScoreBadge deal={deal} />
                  </span>
                </h3>
                <PlBreakdown deal={deal} marketSource={mk.source} />
              </div>
            </>
          ) : (
            <div className="banner" style={{ marginTop: 16 }}>
              このカードに現在アクティブな仕入れ案件はありません(相場ウォッチのみ)。
            </div>
          )}

          <div className="drawer-section">
            <h3>What-if シミュレータ</h3>
            <WhatIf
              mode={whatifMode}
              initialBuy={Math.round(initialBuy)}
              initialSell={whatifMode === "mercari" ? Math.round(latestSell) : Math.round(latestSell * 100) / 100}
              fx={fx}
              model={model}
              source={whatifSource}
            />
            <p className="planner-note">
              {whatifMode === "mercari"
                ? `メルカリ販売手数料 ${fmtPct(mercariSell.fee_rate, 0)}・発送送料 ${fmtYen(mercariSell.shipping_jpy)} で計算(メルカリ内完結のため為替は関与しません)。`
                : `為替 ${fx ? fx.toFixed(2) : "—"} 円/$、eBay手数料・送料は summary.json の profit_model と同一パラメータで計算。`}
            </p>
          </div>

          <div className="drawer-section">
            <h3 style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 4 }}>
              価格チャート
              {ebayPts.length > 0 && mercPts.length > 0 && (
                <span className="range-chips" role="group" aria-label="相場ソース切替">
                  {[
                    { id: "ebay", label: "eBay $" },
                    { id: "mercari", label: "メルカリ ¥" },
                  ].map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`filter-chip${series === s.id ? " active" : ""}`}
                      onClick={() => setSeriesChoice(s.id)}
                    >
                      {s.label}
                    </button>
                  ))}
                </span>
              )}
              <span className="range-chips" role="group" aria-label="表示期間">
                {[30, 60, 90].map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={`filter-chip${range === d ? " active" : ""}`}
                    onClick={() => setRange(d)}
                  >
                    {d}日
                  </button>
                ))}
              </span>
            </h3>
            <PriceChart points={chartPoints} currency={chartCurrency} />
          </div>

          <div className="drawer-section">
            <h3>直近スナップショット(10日)</h3>
            {snaps.length === 0 ? (
              <div className="chart-placeholder">このカードの相場履歴はまだありません</div>
            ) : (
              <table className="snap-table">
                <thead>
                  <tr>
                    <th scope="col">日付</th>
                    <th scope="col">中央値</th>
                    <th scope="col">レンジ</th>
                    <th scope="col">件数</th>
                  </tr>
                </thead>
                <tbody>
                  {snaps.map((p) => (
                    <tr key={p.date}>
                      <td>{p.date}</td>
                      <td>{fmtMarket(p.median, chartCurrency)}</td>
                      <td>
                        {fmtMarket(p.min, chartCurrency)}〜{fmtMarket(p.max, chartCurrency)}
                      </td>
                      <td>{p.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {others.length > 0 && (
            <div className="drawer-section">
              <h3>他の仕入れ候補({others.length}件)</h3>
              {others.map((d) => (
                <button key={dealKey(d)} type="button" className="alt-row" onClick={() => onSelectDeal(d)}>
                  <span className="chip">{sourceLabel(d.source)}</span>
                  <span className="ar-main">
                    <span className="num" style={{ fontWeight: 600 }}>
                      {fmtYen(d.buy_price_jpy)}
                    </span>
                    <span className="muted" style={{ marginLeft: 8, fontSize: 11 }}>
                      {d.title}
                    </span>
                  </span>
                  <span className={`num ${d.profit_jpy >= 0 ? "pos" : "neg"}`} style={{ fontWeight: 700 }}>
                    {fmtSignedYen(d.profit_jpy)}
                  </span>
                  <ScoreBadge deal={d} />
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
