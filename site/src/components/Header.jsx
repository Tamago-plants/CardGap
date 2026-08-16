// ヘッダ: タイトル + 更新日時 + USD/JPYレート。
import { fmtDateTimeJst } from "../format.js";

export default function Header({ summary }) {
  const generatedAt = summary?.generated_at || null;
  const fxRate = summary?.fx_rate ?? null;
  return (
    <header className="site-header">
      <h1>CardGap</h1>
      <span className="tagline">トレカ相場乖離ダッシュボード</span>
      <div className="header-meta">
        <span>
          更新: <strong>{generatedAt ? fmtDateTimeJst(generatedAt) : "—"}</strong>
        </span>
        <span>
          USD/JPY: <strong>{fxRate != null ? fxRate.toFixed(2) : "—"}</strong>
        </span>
      </div>
    </header>
  );
}
