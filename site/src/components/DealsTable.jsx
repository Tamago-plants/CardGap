// 案件テーブル(メイン)。deals.json の全件をフィルタ・ソートして表示する。
// フィルタ行はテーブル上に1行: カテゴリ / confidence / PSAのみ / 信頼度low含む / 最低利益率。
// 列ヘッダ(利益率・実質利益・仕入価格)クリックで昇降順を切り替える。
import { useMemo, useState } from "react";
import {
  categoryLabel,
  fmtPct,
  fmtUsd,
  fmtYen,
  sourceLabel,
} from "../format.js";

const CONFIDENCES = ["high", "medium", "low"];

// ソート可能列: キー → deals の数値フィールド
const SORT_FIELDS = {
  profit_rate: "profit_rate",
  profit_jpy: "profit_jpy",
  buy_price_jpy: "buy_price_jpy",
};

function dealKey(deal) {
  return `${deal.card_id}::${deal.source}::${deal.listing_url}`;
}

function Thumb({ url, alt }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return <span className="thumb-placeholder">画像</span>;
  }
  return (
    <img
      className="thumb"
      src={url}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

export default function DealsTable({ deals, selectedDeal, onSelect }) {
  // ---- フィルタ状態 ----
  const [category, setCategory] = useState("all");
  const [confChecked, setConfChecked] = useState(
    () => new Set(CONFIDENCES) // 初期状態は全confidence表示
  );
  const [psaOnly, setPsaOnly] = useState(false);
  const [includeLowReliability, setIncludeLowReliability] = useState(true);
  const [minRateInput, setMinRateInput] = useState(""); // %入力(空=フィルタなし)

  // ---- ソート状態(初期: 利益率の降順 = export の並びと同じ) ----
  const [sortKey, setSortKey] = useState("profit_rate");
  const [sortDesc, setSortDesc] = useState(true);

  const categories = useMemo(
    () => [...new Set(deals.map((d) => d.category))].sort(),
    [deals]
  );

  const toggleConf = (c) => {
    setConfChecked((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  };

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDesc((d) => !d); // 同じ列を再クリック → 昇降順トグル
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  const filtered = useMemo(() => {
    const minRate = minRateInput === "" ? null : Number(minRateInput) / 100;
    const rows = deals.filter((d) => {
      if (category !== "all" && d.category !== category) return false;
      if (!confChecked.has(d.confidence)) return false;
      if (psaOnly && d.psa_grade == null) return false;
      if (!includeLowReliability && d.reliability !== "ok") return false;
      if (minRate != null && !Number.isNaN(minRate) && d.profit_rate < minRate)
        return false;
      return true;
    });
    const field = SORT_FIELDS[sortKey] || "profit_rate";
    rows.sort((a, b) => {
      const av = a[field] ?? 0;
      const bv = b[field] ?? 0;
      return sortDesc ? bv - av : av - bv;
    });
    return rows;
  }, [deals, category, confChecked, psaOnly, includeLowReliability, minRateInput, sortKey, sortDesc]);

  const sortMark = (key) =>
    sortKey === key ? (sortDesc ? " ▼" : " ▲") : "";

  return (
    <section className="card">
      <h2>案件一覧</h2>

      {/* フィルタ行 */}
      <div className="filter-row">
        <label>
          カテゴリ
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="all">すべて</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(c)}
              </option>
            ))}
          </select>
        </label>
        <span className="filter-group">
          <span className="group-label">confidence:</span>
          {CONFIDENCES.map((c) => (
            <label key={c}>
              <input
                type="checkbox"
                checked={confChecked.has(c)}
                onChange={() => toggleConf(c)}
              />
              {c}
            </label>
          ))}
        </span>
        <label>
          <input
            type="checkbox"
            checked={psaOnly}
            onChange={(e) => setPsaOnly(e.target.checked)}
          />
          PSAのみ
        </label>
        <label>
          <input
            type="checkbox"
            checked={includeLowReliability}
            onChange={(e) => setIncludeLowReliability(e.target.checked)}
          />
          信頼度low含む
        </label>
        <label>
          最低利益率
          <input
            type="number"
            step="1"
            placeholder="—"
            value={minRateInput}
            onChange={(e) => setMinRateInput(e.target.value)}
          />
          %
        </label>
        <span className="section-note">{filtered.length} / {deals.length} 件</span>
      </div>

      {deals.length === 0 ? (
        <p className="empty-note">案件がありません</p>
      ) : filtered.length === 0 ? (
        <p className="empty-note">フィルタ条件に合う案件がありません</p>
      ) : (
        <div className="table-wrap">
          <table className="deals">
            <thead>
              <tr>
                <th>画像</th>
                <th>カード名</th>
                <th>仕入元</th>
                <th
                  className="num sortable"
                  onClick={() => handleSort("buy_price_jpy")}
                  title="クリックで並べ替え"
                >
                  仕入価格¥{sortMark("buy_price_jpy")}
                </th>
                <th className="num">eBay中央値$ (件数)</th>
                <th
                  className="num sortable"
                  onClick={() => handleSort("profit_jpy")}
                  title="クリックで並べ替え"
                >
                  実質利益¥{sortMark("profit_jpy")}
                </th>
                <th
                  className="num sortable"
                  onClick={() => handleSort("profit_rate")}
                  title="クリックで並べ替え"
                >
                  利益率%{sortMark("profit_rate")}
                </th>
                <th>confidence</th>
                <th>相場信頼度</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => {
                const key = dealKey(d);
                const selected =
                  selectedDeal && dealKey(selectedDeal) === key;
                return (
                  <tr
                    key={key}
                    className={selected ? "selected" : undefined}
                    onClick={() => onSelect(d)}
                  >
                    <td>
                      <Thumb url={d.image_url} alt={d.display_name} />
                    </td>
                    <td>
                      <div className="deal-name" title={d.display_name}>
                        {d.display_name}
                      </div>
                    </td>
                    <td>{sourceLabel(d.source)}</td>
                    <td className="num">{fmtYen(d.buy_price_jpy)}</td>
                    <td className="num">
                      {fmtUsd(d.ebay_median_usd)} ({d.ebay_count_30d})
                    </td>
                    <td
                      className={
                        "num " + (d.profit_jpy >= 0 ? "profit-pos" : "profit-neg")
                      }
                    >
                      {fmtYen(d.profit_jpy)}
                    </td>
                    <td
                      className={
                        "num " + (d.profit_rate >= 0 ? "profit-pos" : "profit-neg")
                      }
                    >
                      {fmtPct(d.profit_rate)}
                    </td>
                    <td>
                      <span className={`badge conf-${d.confidence}`}>
                        {d.confidence}
                      </span>
                    </td>
                    <td>
                      <span className={`badge rel-${d.reliability}`}>
                        {d.reliability === "ok" ? "OK" : "低"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
