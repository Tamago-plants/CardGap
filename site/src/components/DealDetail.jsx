// 詳細パネル: 選択された案件のカード情報 + 損益内訳 + 価格推移チャート。
// テーブル行クリックで開き、表示時に自動でスクロールする。
import { useEffect, useRef } from "react";
import PriceChart from "./PriceChart.jsx";
import {
  categoryLabel,
  fmtDateTimeJst,
  fmtPct,
  fmtUsd,
  fmtYen,
  sourceLabel,
} from "../format.js";

export default function DealDetail({ deal, historyCard, onClose }) {
  const ref = useRef(null);

  // 案件を切り替えたらパネルまでスクロール
  useEffect(() => {
    if (ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [deal]);

  // 送料は deals.json に含まれないので損益の恒等式から逆算する:
  //   profit = revenue - fees - ship_out - buy_total
  const shipOut =
    deal.revenue_jpy != null &&
    deal.ebay_fees_jpy != null &&
    deal.buy_total_jpy != null &&
    deal.profit_jpy != null
      ? deal.revenue_jpy - deal.ebay_fees_jpy - deal.buy_total_jpy - deal.profit_jpy
      : null;

  const points = historyCard?.points || [];

  return (
    <section className="card" ref={ref}>
      <div className="detail-head">
        <h2>{deal.display_name}</h2>
        <button type="button" className="detail-close" onClick={onClose}>
          閉じる ✕
        </button>
      </div>

      <div className="detail-grid">
        {deal.image_url ? (
          <img
            className="detail-image"
            src={deal.image_url}
            alt={deal.display_name}
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        ) : (
          <div className="detail-image" />
        )}

        <div className="detail-info">
          <dl>
            <dt>英語名</dt>
            <dd>{deal.name_en || "—"}</dd>
            <dt>カテゴリ</dt>
            <dd>{categoryLabel(deal.category)}</dd>
            <dt>出品タイトル</dt>
            <dd>{deal.title || "—"}</dd>
            <dt>仕入元</dt>
            <dd>
              {/* 外部リンクは必ず新規タブ + noopener noreferrer */}
              <a
                href={deal.listing_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {sourceLabel(deal.source)}で見る ↗
              </a>
            </dd>
            <dt>eBay相場</dt>
            <dd>
              中央値 {fmtUsd(deal.ebay_median_usd)}(直近30日 {deal.ebay_count_30d} 件、
              {fmtUsd(deal.ebay_min_usd)}〜{fmtUsd(deal.ebay_max_usd)})
            </dd>
            <dt>マッチ確度</dt>
            <dd>
              <span className={`badge conf-${deal.confidence}`}>{deal.confidence}</span>{" "}
              / 相場信頼度{" "}
              <span className={`badge rel-${deal.reliability}`}>
                {deal.reliability === "ok" ? "OK" : "低"}
              </span>
            </dd>
            <dt>計算日時</dt>
            <dd>
              {fmtDateTimeJst(deal.computed_at)}(USD/JPY{" "}
              {deal.fx_rate != null ? deal.fx_rate.toFixed(2) : "—"})
            </dd>
          </dl>
        </div>

        <div className="pnl">
          <h3>損益内訳</h3>
          <table>
            <tbody>
              <tr>
                <td>想定売上(為替マージン後)</td>
                <td className="num">{fmtYen(deal.revenue_jpy)}</td>
              </tr>
              <tr>
                <td>eBay手数料</td>
                <td className="num">-{fmtYen(deal.ebay_fees_jpy)}</td>
              </tr>
              <tr>
                <td>送料(発送)</td>
                <td className="num">{shipOut != null ? "-" + fmtYen(shipOut) : "—"}</td>
              </tr>
              <tr>
                <td>仕入総額(価格+手数料+送料)</td>
                <td className="num">-{fmtYen(deal.buy_total_jpy)}</td>
              </tr>
              <tr className="total">
                <td>実質利益</td>
                <td
                  className={
                    "num " + (deal.profit_jpy >= 0 ? "profit-pos" : "profit-neg")
                  }
                >
                  {fmtYen(deal.profit_jpy)}({fmtPct(deal.profit_rate)})
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="chart-block">
        <h3>価格推移(eBay中央値 $ / 直近{points.length}日分のスナップショット)</h3>
        <PriceChart points={points} />
      </div>
    </section>
  );
}
