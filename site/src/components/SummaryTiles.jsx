// サマリタイル3枚: 閾値超え案件数 / 全案件数 / 直近の収集失敗数。
// 収集失敗数は summary.scrape_health の queries_failed + parse_failures の合計。
import { fmtPct, fmtYen } from "../format.js";

export default function SummaryTiles({ summary, hasData }) {
  const above = summary?.deal_count_above_threshold ?? 0;
  const total = summary?.deal_count_total ?? 0;
  const health = summary?.scrape_health || [];
  const failures = health.reduce(
    (acc, h) => acc + (h.queries_failed || 0) + (h.parse_failures || 0),
    0
  );
  const th = summary?.thresholds || {};

  return (
    <div className="tiles">
      <div className="tile">
        <div className="tile-label">閾値超え案件</div>
        <div className="tile-value">{above}</div>
        <div className="tile-sub">
          利益 {fmtYen(th.min_profit_jpy)} 以上・利益率 {fmtPct(th.min_profit_rate, 0)} 以上
        </div>
      </div>
      <div className="tile">
        <div className="tile-label">全案件</div>
        <div className="tile-value">{total}</div>
        <div className="tile-sub">無視リスト除外後の全マッチ</div>
      </div>
      <div className="tile">
        <div className="tile-label">直近の収集失敗</div>
        {/* データ未投入(scrape_health が空)なら "—"、0件なら "正常" */}
        {!hasData || health.length === 0 ? (
          <div className="tile-value">—</div>
        ) : failures === 0 ? (
          <div className="tile-value ok">正常</div>
        ) : (
          <div className="tile-value bad">{failures}</div>
        )}
        <div className="tile-sub">クエリ失敗 + 解析失敗の合計</div>
      </div>
    </div>
  );
}
