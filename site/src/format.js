// 表示用フォーマッタとラベル辞書。
// 金額・割合・日時の見た目はすべてここに集約する(コンポーネント側で個別整形しない)。

/** 円: ¥12,345(null/undefined は "—") */
export function fmtYen(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return "¥" + Math.round(v).toLocaleString("ja-JP");
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
  const s = (rate * 100).toFixed(digits);
  return (rate > 0 ? "+" : "") + s + "%";
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

/** "YYYY-MM-DD" → "M/D"(チャート軸用の短い表記) */
export function fmtDateShort(dateStr) {
  if (!dateStr) return "";
  const parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  return `${Number(parts[1])}/${Number(parts[2])}`;
}

// カテゴリ / 仕入元の表示名(未知の値はそのまま表示)
const CATEGORY_LABELS = { pokemon: "ポケモン", naruto: "ナルト" };
const SOURCE_LABELS = { mercari: "メルカリ", snkrdunk: "スニダン" };

export function categoryLabel(cat) {
  return CATEGORY_LABELS[cat] || cat || "—";
}

export function sourceLabel(src) {
  return SOURCE_LABELS[src] || src || "—";
}
