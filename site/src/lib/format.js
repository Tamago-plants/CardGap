// 表示用フォーマッタとラベル辞書。
// 金額・割合・日時の見た目はすべてここに集約する(コンポーネント側で個別整形しない)。

/** 円: ¥12,345(null/undefined は "—") */
export function fmtYen(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return "¥" + Math.round(v).toLocaleString("ja-JP");
}

/** 符号付き円: +¥12,345 / −¥3,000 */
export function fmtSignedYen(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = "¥" + Math.abs(Math.round(v)).toLocaleString("ja-JP");
  return (v >= 0 ? "+" : "−") + abs;
}

/** ドル: $123.45 */
export function fmtUsd(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return (
    "$" +
    v.toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
  );
}

/** 利益率など(0.235 → "23.5%") */
export function fmtPct(rate, digits = 1) {
  if (rate == null || Number.isNaN(rate)) return "—";
  return (rate * 100).toFixed(digits) + "%";
}

/** 符号付き%(騰落用。0.052 → "+5.2%") */
export function fmtSignedPct(rate, digits = 1) {
  if (rate == null || Number.isNaN(rate)) return "—";
  const s = (Math.abs(rate) * 100).toFixed(digits);
  return (rate >= 0 ? "+" : "−") + s + "%";
}

/** ISO日時 → 日本時間の "2025/01/02 09:30" 表記 */
export function fmtDateTimeJst(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    d.toLocaleString("ja-JP", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }) + " JST"
  );
}

/** ISO日時 → 相対表示("3時間前"など)。未来や不正値は "—" */
export function fmtRelative(iso, nowMs = Date.now()) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Math.max(0, nowMs - t);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "たった今";
  if (min < 60) return `${min}分前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}時間前`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}日前`;
  return `${Math.floor(d / 30)}ヶ月前`;
}

/** "YYYY-MM-DD" → "M/D"(チャート軸用の短い表記) */
export function fmtDateShort(dateStr) {
  if (!dateStr) return "";
  const parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  return `${Number(parts[1])}/${Number(parts[2])}`;
}

/** 回転目安: 30日÷件数 → "約N日/枚"(0件は "—") */
export function fmtTurnover(count30d) {
  if (!count30d || count30d <= 0) return "—";
  const days = 30 / count30d;
  return `約${days >= 10 ? Math.round(days) : days.toFixed(1)}日/枚`;
}

// カテゴリ / 仕入元 / 確度などの表示名(未知の値はそのまま表示)
const CATEGORY_LABELS = { pokemon: "ポケモン", naruto: "ナルト", onepiece: "ワンピース", yugioh: "遊戯王" };
const SOURCE_LABELS = { mercari: "メルカリ", snkrdunk: "スニダン" };
const CONFIDENCE_LABELS = { high: "確度high", medium: "確度med", low: "確度low" };
const RELIABILITY_LABELS = { ok: "信頼ok", low: "信頼low" };

export function categoryLabel(cat) {
  return CATEGORY_LABELS[cat] || cat || "—";
}

export function sourceLabel(src) {
  return SOURCE_LABELS[src] || src || "—";
}

export function confidenceLabel(c) {
  return CONFIDENCE_LABELS[c] || c || "—";
}

export function reliabilityLabel(r) {
  return RELIABILITY_LABELS[r] || r || "—";
}
