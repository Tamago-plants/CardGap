// 案件一覧(スクリーナー本体)。
// クイックフィルタチップ + 詳細フィルタポップオーバー + 高密度テーブル。
// フィルタ・ソート状態は hash クエリに反映され、リロード/共有に耐える。
// モバイル(〜768px)は CSS でカードリスト表示に切り替わる。
import { useEffect, useMemo, useRef, useState } from "react";
import CardThumb from "./CardThumb.jsx";
import HoverTip from "./HoverTip.jsx";
import ScoreBadge from "./ScoreBadge.jsx";
import Sparkline from "./Sparkline.jsx";
import SpreadBar from "./SpreadBar.jsx";
import {
  categoryLabel,
  confidenceLabel,
  fmtPct,
  fmtSignedPct,
  fmtSignedYen,
  fmtTurnover,
  fmtUsd,
  fmtYen,
  reliabilityLabel,
  sourceLabel,
} from "../lib/format.js";
import { isAboveThreshold, isNewDeal, medianSeries } from "../lib/data.js";
import { opportunityScore } from "../lib/score.js";

const QUICK = [
  { id: "above", label: "閾値超え" },
  { id: "new", label: "NEW" },
  { id: "psa", label: "PSAのみ" },
  { id: "high", label: "high確度" },
];
const SOURCES = ["mercari", "snkrdunk"];
const SORTS = {
  score: { label: "スコア", get: (r) => r.score },
  rate: { label: "利益率", get: (r) => r.deal.profit_rate ?? -99 },
  profit: { label: "利益", get: (r) => r.deal.profit_jpy ?? -9e9 },
  buy: { label: "仕入価格", get: (r) => r.deal.buy_price_jpy ?? 0 },
  count: { label: "件数", get: (r) => r.deal.ebay_count_30d ?? 0 },
};

const splitCsv = (s) => (s ? s.split(",").filter(Boolean) : []);

/** フィルタ適用後の行を CSV にして client-side でダウンロード */
function exportCsv(rows) {
  const head = [
    "カード名", "カテゴリ", "仕入元", "仕入価格JPY", "仕入総額JPY", "eBay中央値USD",
    "30日件数", "想定売上JPY", "実質利益JPY", "利益率", "スコア", "確度", "信頼度", "出品URL",
  ];
  const esc = (v) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [head.join(",")];
  for (const r of rows) {
    const d = r.deal;
    lines.push(
      [
        d.display_name, d.category, d.source, d.buy_price_jpy, d.buy_total_jpy,
        d.ebay_median_usd, d.ebay_count_30d, d.revenue_jpy, d.profit_jpy,
        d.profit_rate, r.score, d.confidence, d.reliability, d.listing_url,
      ].map(esc).join(",")
    );
  }
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `cardgap-deals-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** 詳細フィルタポップオーバー */
function FilterPopover({ params, setParams, categories, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const cats = splitCsv(params.cat);
  const confs = splitCsv(params.conf);
  const toggleIn = (key, list, v) => {
    const next = list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
    setParams({ [key]: next.join(",") || null });
  };
  const mr = params.mr != null && params.mr !== "" ? Number(params.mr) : "";
  const mp = params.mp != null && params.mp !== "" ? Number(params.mp) : "";

  return (
    <div className="popover" ref={ref} role="dialog" aria-label="詳細フィルタ">
      <div className="pop-group">
        <h4>カテゴリ</h4>
        {categories.map((c) => (
          <label key={c} className="cb">
            <input type="checkbox" checked={cats.includes(c)} onChange={() => toggleIn("cat", cats, c)} />
            {categoryLabel(c)}
          </label>
        ))}
      </div>
      <div className="pop-group">
        <h4>確度</h4>
        {["high", "medium", "low"].map((c) => (
          <label key={c} className="cb">
            <input type="checkbox" checked={confs.includes(c)} onChange={() => toggleIn("conf", confs, c)} />
            {c}
          </label>
        ))}
      </div>
      <div className="pop-group">
        <h4>信頼度</h4>
        <label className="cb">
          <input
            type="checkbox"
            checked={params.rel === "ok"}
            onChange={() => setParams({ rel: params.rel === "ok" ? null : "ok" })}
          />
          ok のみ
        </label>
      </div>
      <div className="pop-group">
        <h4>最低利益率(%)</h4>
        <div className="pop-row">
          <input
            type="range"
            min="-50"
            max="100"
            step="5"
            value={mr === "" ? -50 : mr}
            onChange={(e) => setParams({ mr: e.target.value === "-50" ? null : e.target.value })}
            aria-label="最低利益率スライダー"
          />
          <input
            type="number"
            step="5"
            placeholder="指定なし"
            value={mr}
            onChange={(e) => setParams({ mr: e.target.value === "" ? null : e.target.value })}
            aria-label="最低利益率"
          />
        </div>
      </div>
      <div className="pop-group">
        <h4>最低利益額(円)</h4>
        <input
          type="number"
          step="1000"
          placeholder="指定なし"
          value={mp}
          onChange={(e) => setParams({ mp: e.target.value === "" ? null : e.target.value })}
          aria-label="最低利益額"
        />
      </div>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => setParams({ cat: null, conf: null, rel: null, mr: null, mp: null })}
      >
        詳細フィルタをクリア
      </button>
    </div>
  );
}

export default function DealsScreen({ deals, history, summary, params, setParams, onOpenDeal }) {
  const [popOpen, setPopOpen] = useState(false);
  const thresholds = summary && summary.thresholds;
  const generatedAt = summary && summary.generated_at;

  const flags = splitCsv(params.f);
  const srcs = splitCsv(params.src);
  const sortKey = SORTS[params.sort] ? params.sort : "score";
  const sortDir = params.dir === "asc" ? "asc" : "desc";

  const histMap = useMemo(() => {
    const m = new Map();
    for (const c of (history && history.cards) || []) m.set(c.card_id, c);
    return m;
  }, [history]);

  const categories = useMemo(() => Array.from(new Set(deals.map((d) => d.category).filter(Boolean))), [deals]);

  const rows = useMemo(() => {
    const cats = splitCsv(params.cat);
    const confs = splitCsv(params.conf);
    const mr = params.mr != null && params.mr !== "" ? Number(params.mr) / 100 : null;
    const mp = params.mp != null && params.mp !== "" ? Number(params.mp) : null;
    let list = deals.map((d) => ({ deal: d, score: opportunityScore(d) }));
    if (flags.includes("above")) list = list.filter((r) => isAboveThreshold(r.deal, thresholds));
    if (flags.includes("new")) list = list.filter((r) => isNewDeal(r.deal, generatedAt));
    if (flags.includes("psa")) list = list.filter((r) => r.deal.psa_grade != null);
    if (flags.includes("high")) list = list.filter((r) => r.deal.confidence === "high");
    if (srcs.length > 0) list = list.filter((r) => srcs.includes(r.deal.source));
    if (cats.length > 0) list = list.filter((r) => cats.includes(r.deal.category));
    if (confs.length > 0) list = list.filter((r) => confs.includes(r.deal.confidence));
    if (params.rel === "ok") list = list.filter((r) => r.deal.reliability === "ok");
    if (mr != null && !Number.isNaN(mr)) list = list.filter((r) => (r.deal.profit_rate ?? -99) >= mr);
    if (mp != null && !Number.isNaN(mp)) list = list.filter((r) => (r.deal.profit_jpy ?? -9e9) >= mp);
    const get = SORTS[sortKey].get;
    list.sort((a, b) => (sortDir === "asc" ? get(a) - get(b) : get(b) - get(a)));
    return list;
  }, [deals, params.f, params.src, params.cat, params.conf, params.rel, params.mr, params.mp, sortKey, sortDir, thresholds, generatedAt]);

  const toggleFlag = (id) => {
    const next = flags.includes(id) ? flags.filter((f) => f !== id) : [...flags, id];
    setParams({ f: next.join(",") || null });
  };
  const toggleSrc = (s) => {
    const next = srcs.includes(s) ? srcs.filter((x) => x !== s) : [...srcs, s];
    setParams({ src: next.join(",") || null });
  };
  const clearAll = () => setParams({ f: null, src: null, cat: null, conf: null, rel: null, mr: null, mp: null });
  const anyFilter =
    flags.length > 0 || srcs.length > 0 || params.cat || params.conf || params.rel || params.mr || params.mp;

  const onSort = (key) => {
    if (sortKey === key) {
      setParams({ dir: sortDir === "desc" ? "asc" : null });
    } else {
      setParams({ sort: key === "score" ? null : key, dir: null });
    }
  };
  const arrow = (key) => (sortKey === key ? <span className="sort-arrow">{sortDir === "desc" ? "▼" : "▲"}</span> : null);

  const activeLabels = [
    ...flags.map((f) => (QUICK.find((q) => q.id === f) || {}).label).filter(Boolean),
    ...srcs.map(sourceLabel),
    ...(params.cat ? splitCsv(params.cat).map(categoryLabel) : []),
    ...(params.conf ? splitCsv(params.conf).map((c) => `確度${c}`) : []),
    ...(params.rel === "ok" ? ["信頼ok"] : []),
    ...(params.mr ? [`利益率≥${params.mr}%`] : []),
    ...(params.mp ? [`利益≥${fmtYen(Number(params.mp))}`] : []),
  ];

  return (
    <>
      <div className="deals-toolbar">
        <button type="button" className={`filter-chip${!anyFilter ? " active" : ""}`} onClick={clearAll}>
          すべて
        </button>
        {QUICK.map((q) => (
          <button
            key={q.id}
            type="button"
            className={`filter-chip${flags.includes(q.id) ? " active" : ""}`}
            onClick={() => toggleFlag(q.id)}
          >
            {q.label}
          </button>
        ))}
        {SOURCES.map((s) => (
          <button
            key={s}
            type="button"
            className={`filter-chip${srcs.includes(s) ? " active" : ""}`}
            onClick={() => toggleSrc(s)}
          >
            {sourceLabel(s)}
          </button>
        ))}
        <div className="toolbar-right">
          <div className="popover-anchor">
            <button
              type="button"
              className={`btn btn-sm${popOpen ? " btn-primary" : ""}`}
              aria-expanded={popOpen}
              onClick={() => setPopOpen((o) => !o)}
            >
              詳細フィルタ
            </button>
            {popOpen && (
              <FilterPopover
                params={params}
                setParams={setParams}
                categories={categories}
                onClose={() => setPopOpen(false)}
              />
            )}
          </div>
          <button type="button" className="btn btn-sm" onClick={() => exportCsv(rows)} disabled={rows.length === 0}>
            CSVエクスポート
          </button>
        </div>
      </div>

      <div className="result-info" aria-live="polite">
        {deals.length}件中 {rows.length}件を表示
        {activeLabels.length > 0 ? `(フィルタ: ${activeLabels.join(", ")})` : ""}
        {` ・ ソート: ${SORTS[sortKey].label}${sortDir === "asc" ? "↑" : "↓"}`}
      </div>

      {rows.length === 0 ? (
        <div className="card empty-note">
          {deals.length === 0
            ? "案件データがありません。バッチ実行後に反映されます。"
            : "条件に一致する案件がありません。フィルタを緩めてください。"}
        </div>
      ) : (
        <>
          {/* デスクトップ: 高密度テーブル */}
          <div className="card table-wrap">
            <table className="deals">
              <thead>
                <tr>
                  <th scope="col" aria-label="サムネイル" />
                  <th scope="col">カード</th>
                  <th scope="col" className="num-col sortable" onClick={() => onSort("buy")} aria-sort={sortKey === "buy" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    仕入{arrow("buy")}
                  </th>
                  <th scope="col">
                    <HoverTip
                      ariaLabel="スプレッドバーの説明"
                      tip={
                        <>
                          想定売上を100%とした内訳バー。青=仕入原価 / グレー=手数料+送料 /
                          緑=利益。赤字案件は売上を超えた損失分を赤で表示。各行ホバーで数値内訳。
                        </>
                      }
                    >
                      スプレッド
                    </HoverTip>
                  </th>
                  <th scope="col" className="num-col sortable" onClick={() => onSort("count")} aria-sort={sortKey === "count" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    eBay相場{arrow("count")}
                  </th>
                  <th scope="col">30日推移</th>
                  <th scope="col" className="num-col sortable" onClick={() => onSort("profit")} aria-sort={sortKey === "profit" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    実質利益{arrow("profit")}
                  </th>
                  <th scope="col" className="num-col sortable" onClick={() => onSort("rate")} aria-sort={sortKey === "rate" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    利益率{arrow("rate")}
                  </th>
                  <th scope="col" className="num-col sortable" onClick={() => onSort("score")} aria-sort={sortKey === "score" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    スコア{arrow("score")}
                  </th>
                  <th scope="col">確度/信頼度</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const d = r.deal;
                  const spark = medianSeries(histMap.get(d.card_id), 30);
                  const isNew = isNewDeal(d, generatedAt);
                  return (
                    <tr key={i} onClick={() => onOpenDeal(d)}>
                      <td style={{ width: 48 }}>
                        <CardThumb src={d.image_url} name={d.display_name} />
                      </td>
                      <td className="cell-name">
                        <div className="d-name">
                          <span className="nm">{d.display_name}</span>
                          {isNew && <span className="chip c-new">NEW</span>}
                          {d.psa_grade ? <span className="chip c-psa">PSA{Math.round(d.psa_grade)}</span> : null}
                        </div>
                        <div className="d-title">{d.title}</div>
                      </td>
                      <td className="cell-buy num-col">
                        <span className="chip">{sourceLabel(d.source)}</span>{" "}
                        <span className="buy-price">{fmtYen(d.buy_price_jpy)}</span>
                      </td>
                      <td>
                        <SpreadBar deal={d} />
                      </td>
                      <td className="cell-market num-col">
                        <span className="mk-median">{fmtUsd(d.ebay_median_usd)}</span>{" "}
                        <span className="count-badge">{d.ebay_count_30d}件</span>
                        <div className="mk-sub">{fmtTurnover(d.ebay_count_30d)}</div>
                      </td>
                      <td>
                        <Sparkline values={spark} />
                      </td>
                      <td className={`cell-profit num-col ${d.profit_jpy >= 0 ? "pos" : "neg"}`}>
                        {fmtSignedYen(d.profit_jpy)}
                      </td>
                      <td className="cell-rate num-col">
                        <div className="rate-line">
                          <span className={d.profit_rate >= 0 ? "pos" : "neg"}>{fmtSignedPct(d.profit_rate)}</span>
                          <span className="ratebar" aria-hidden="true">
                            <i
                              style={{
                                left: 0,
                                width: `${Math.min(100, Math.abs(d.profit_rate || 0) * 100)}%`,
                                background: d.profit_rate >= 0 ? "var(--pos)" : "var(--neg)",
                              }}
                            />
                          </span>
                        </div>
                      </td>
                      <td className="num-col">
                        <ScoreBadge deal={d} />
                      </td>
                      <td>
                        <span className={`chip c-${d.confidence}`}>{confidenceLabel(d.confidence)}</span>{" "}
                        <span className={`chip ${d.reliability === "ok" ? "" : "c-low"}`}>
                          {reliabilityLabel(d.reliability)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* モバイル: カードリスト */}
          <div className="cards-list">
            {rows.map((r, i) => {
              const d = r.deal;
              const isNew = isNewDeal(d, generatedAt);
              return (
                <button key={i} type="button" className="card deal-card" onClick={() => onOpenDeal(d)}>
                  <CardThumb src={d.image_url} name={d.display_name} size="lg" />
                  <span className="dc-body">
                    <span className="dc-name">
                      <span className="nm">{d.display_name}</span>
                      {isNew && <span className="chip c-new">NEW</span>}
                    </span>
                    <span className="dc-row">
                      <span className="chip">{sourceLabel(d.source)}</span>
                      <span className="num">{fmtYen(d.buy_price_jpy)}</span>
                      <span className="muted">→</span>
                      <span className="num">{fmtUsd(d.ebay_median_usd)}</span>
                    </span>
                    <span className="dc-row">
                      <span className={`dc-profit ${d.profit_jpy >= 0 ? "pos" : "neg"}`}>
                        {fmtSignedYen(d.profit_jpy)}
                      </span>
                      <span className={`num ${d.profit_rate >= 0 ? "pos" : "neg"}`}>{fmtSignedPct(d.profit_rate)}</span>
                      <ScoreBadge deal={d} />
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
