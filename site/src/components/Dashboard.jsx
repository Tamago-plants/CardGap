// ダッシュボード(着地画面): KPIタイル / 本日のベストディール / 急騰・急落 / 新着案件。
// データ未投入(generated_at null)のときはオンボーディングカードを出す。
import { useMemo, useState } from "react";
import CardThumb from "./CardThumb.jsx";
import HoverTip from "./HoverTip.jsx";
import ScoreBadge from "./ScoreBadge.jsx";
import {
  fmtPct,
  fmtSignedPct,
  fmtSignedYen,
  fmtUsd,
  fmtYen,
  sourceLabel,
} from "../lib/format.js";
import { isAboveThreshold, isNewDeal } from "../lib/data.js";
import { opportunityScore } from "../lib/score.js";

/** データ未投入時のオンボーディング */
function Onboarding() {
  const cmd = "python -m cardgap run && git add site/public/data && git commit -m 'data' && git push";
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard 不可の環境では何もしない */
    }
  };
  return (
    <div className="card onboard">
      <span className="onboard-icon" aria-hidden="true">
        C
      </span>
      <h2>まだデータが投入されていません</h2>
      <p>
        自宅PC側で日次バッチを実行して <code>site/public/data/</code> のJSONを push すると、
        このダッシュボードに案件と相場が表示されます。
      </p>
      <div className="onboard-cmd">
        <code>{cmd}</code>
        <button type="button" className="btn btn-sm" onClick={copy}>
          {copied ? "コピー済み" : "コピー"}
        </button>
      </div>
      <ol className="onboard-steps">
        <li>eBay Sold / メルカリ / スニダンを巡回して相場と出品を収集</li>
        <li>損益モデルで日米間の利ざやを計算し、deals/history/summary をエクスポート</li>
        <li>push すると GitHub Actions がサイトを再ビルドして反映</li>
      </ol>
    </div>
  );
}

/** 収集ステータスの failed 集計 */
function healthInfo(summary) {
  const runs = (summary && summary.scrape_health) || [];
  const failed = runs.reduce((a, r) => a + (r.queries_failed || 0), 0);
  return { runs, failed };
}

export default function Dashboard({ deals, summary, noData, onOpenDeal, onOpenCard }) {
  const thresholds = summary && summary.thresholds;
  const generatedAt = summary && summary.generated_at;

  const above = useMemo(() => deals.filter((d) => isAboveThreshold(d, thresholds)), [deals, thresholds]);
  const best = useMemo(
    () =>
      deals
        .map((d) => ({ d, s: opportunityScore(d) }))
        .sort((a, b) => b.s - a.s)
        .slice(0, 3),
    [deals]
  );
  const newDeals = useMemo(
    () => deals.filter((d) => isNewDeal(d, generatedAt)).sort((a, b) => opportunityScore(b) - opportunityScore(a)),
    [deals, generatedAt]
  );
  const bestRate = above.length > 0 ? Math.max(...above.map((d) => d.profit_rate)) : null;
  const bestRateDeal = above.find((d) => d.profit_rate === bestRate);
  const sumProfit = above.reduce((a, d) => a + (d.profit_jpy || 0), 0);
  const { runs, failed } = healthInfo(summary);

  if (noData) return <Onboarding />;

  const minRatePct = thresholds ? Math.round((thresholds.min_profit_rate || 0) * 100) : 20;
  const minProfit = thresholds ? thresholds.min_profit_jpy || 0 : 5000;

  return (
    <>
      {/* KPI タイル */}
      <div className="kpi-grid">
        <div className="card kpi">
          <div className="kpi-label">
            閾値超え案件
            <HoverTip
              className="info-i"
              ariaLabel="閾値の条件"
              tip={
                <>
                  利益率 {minRatePct}% 以上・利益 {fmtYen(minProfit)} 以上・信頼度 ok・確度
                  high/medium をすべて満たす案件数。
                </>
              }
            >
              i
            </HoverTip>
          </div>
          <div className="kpi-value">
            {above.length}
            <small> / {deals.length}件</small>
          </div>
          <div className="kpi-sub">全案件のうち条件を満たすもの</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">最高利益率</div>
          <div className={`kpi-value ${bestRate != null && bestRate >= 0 ? "pos" : ""}`}>
            {bestRate != null ? fmtSignedPct(bestRate) : "—"}
          </div>
          <div className="kpi-sub">{bestRateDeal ? bestRateDeal.display_name : "閾値超えなし"}</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">閾値超え合計想定利益</div>
          <div className={`kpi-value ${sumProfit >= 0 ? "pos" : "neg"}`}>{fmtYen(sumProfit)}</div>
          <div className="kpi-sub">全て仕入れて売却できた場合の合計</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">収集ステータス</div>
          <div className="kpi-value" style={{ fontSize: 20 }}>
            {failed === 0 ? (
              <>
                <span className="dot ok" aria-hidden="true" /> 正常
              </>
            ) : (
              <HoverTip
                ariaLabel="収集失敗の内訳"
                tip={runs.map((r) => (
                  <span key={r.source} className="tip-row">
                    <span>{sourceLabel(r.source)}</span>
                    <b>
                      {r.queries_failed}/{r.queries_total}失敗
                    </b>
                  </span>
                ))}
              >
                <span style={{ color: "var(--warn-text)" }}>⚠ 失敗{failed}件</span>
              </HoverTip>
            )}
          </div>
          <div className="kpi-sub">
            {runs.length > 0 ? `${runs.length}ソース巡回 / ${runs.reduce((a, r) => a + (r.items_found || 0), 0)}件取得` : "実行履歴なし"}
          </div>
        </div>
      </div>

      {/* 本日のベストディール */}
      <section className="section" aria-label="本日のベストディール">
        <div className="section-head">
          <h2 className="section-title">本日のベストディール</h2>
          <span className="section-sub">Opportunity Score 上位3件</span>
        </div>
        {best.length === 0 || best[0].s === 0 ? (
          <div className="card empty-note">スコアの付く案件がまだありません</div>
        ) : (
          <div className="hero-grid">
            {best.map(({ d, s }, i) => (
              <div
                key={`${d.card_id}-${i}`}
                className="card hero-card"
                role="button"
                tabIndex={0}
                onClick={() => onOpenDeal(d)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onOpenDeal(d);
                  }
                }}
              >
                <span className={`hero-rank m${i + 1}`} aria-label={`${i + 1}位`}>
                  {i + 1}
                </span>
                <CardThumb src={d.image_url} name={d.display_name} size="xl" />
                <div className="hero-body">
                  <div className="hero-name">{d.display_name}</div>
                  <div className="hero-flow">
                    {sourceLabel(d.source)} <b>{fmtYen(d.buy_price_jpy)}</b> → eBay{" "}
                    <b>{fmtUsd(d.ebay_median_usd)}</b>
                  </div>
                  <div className={`hero-profit ${d.profit_jpy >= 0 ? "pos" : "neg"}`}>
                    {fmtSignedYen(d.profit_jpy)}
                    <span className="chip" style={{ marginLeft: 8, verticalAlign: 2 }}>
                      {fmtSignedPct(d.profit_rate)}
                    </span>
                  </div>
                  <div className="hero-meta">
                    <ScoreBadge deal={d} />
                    {isNewDeal(d, generatedAt) && <span className="chip c-new">NEW</span>}
                    {d.psa_grade ? <span className="chip c-psa">PSA{Math.round(d.psa_grade)}</span> : null}
                    <a
                      className="hero-link"
                      href={d.listing_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                    >
                      出品を開く ↗
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 急騰 / 急落 */}
      <section className="section" aria-label="急騰・急落">
        <div className="section-head">
          <h2 className="section-title">急騰 / 急落</h2>
          <span className="section-sub">eBay Sold 中央値の前回スナップショット比</span>
        </div>
        <div className="movers-grid">
          {[
            { label: "急騰", arrow: "▲", list: (summary && summary.movers_up) || [], cls: "pos" },
            { label: "急落", arrow: "▼", list: (summary && summary.movers_down) || [], cls: "neg" },
          ].map((grp) => (
            <div key={grp.label} className="card mover-panel">
              <h3>
                <span className={grp.cls}>{grp.arrow}</span> {grp.label}
              </h3>
              {grp.list.length === 0 ? (
                <div className="empty-note" style={{ padding: "14px 0" }}>
                  比較できるスナップショットがありません
                </div>
              ) : (
                grp.list.map((m) => (
                  <button key={m.card_id} type="button" className="mover-row" onClick={() => onOpenCard(m.card_id)}>
                    <span className="mover-name">{m.display_name}</span>
                    <span className="mover-usd">
                      {fmtUsd(m.prev_median_usd)} → <b>{fmtUsd(m.median_usd)}</b>{" "}
                      <span className="cnt">({m.count}件)</span>
                    </span>
                    <span className={`mover-chg ${m.change_rate >= 0 ? "pos" : "neg"}`}>
                      {m.change_rate >= 0 ? "▲" : "▼"}
                      {fmtSignedPct(m.change_rate)}
                    </span>
                  </button>
                ))
              )}
            </div>
          ))}
        </div>
      </section>

      {/* 新着案件 */}
      <section className="section" aria-label="新着案件">
        <div className="section-head">
          <h2 className="section-title">新着案件</h2>
          <span className="section-sub">初観測から24時間以内</span>
        </div>
        {newDeals.length === 0 ? (
          <div className="card empty-note">直近24時間の新着はありません</div>
        ) : (
          <div className="strip">
            {newDeals.map((d, i) => (
              <button key={`${d.card_id}-${i}`} type="button" className="card strip-card" onClick={() => onOpenDeal(d)}>
                <CardThumb src={d.image_url} name={d.display_name} />
                <span className="strip-body">
                  <span className="strip-name">{d.display_name}</span>
                  <span className={`strip-profit ${d.profit_jpy >= 0 ? "pos" : "neg"}`}>
                    {fmtSignedYen(d.profit_jpy)}{" "}
                    <span className="muted" style={{ fontWeight: 500, fontSize: 11 }}>
                      {fmtPct(d.profit_rate)}
                    </span>
                  </span>
                  <span style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <ScoreBadge deal={d} />
                    <span className="chip c-new">NEW</span>
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
