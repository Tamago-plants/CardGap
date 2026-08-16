// カード画像サムネイル。404などで読めない場合はカード名の頭文字タイルへ
// 自動フォールバックする(onError)。size: "" | "lg" | "xl"
import { useEffect, useState } from "react";

export default function CardThumb({ src, name, size = "" }) {
  const [failed, setFailed] = useState(false);
  // src が変わったらリトライ(ドロワーの内容切替時など)
  useEffect(() => setFailed(false), [src]);

  const cls = `thumb${size ? ` thumb-${size}` : ""}`;
  if (!src || failed) {
    const initial = (name || "?").trim().charAt(0) || "?";
    return (
      <div className={`${cls} thumb-fallback`} role="img" aria-label={name || "カード画像なし"}>
        {initial}
      </div>
    );
  }
  return (
    <img
      className={cls}
      src={src}
      alt={name || "カード画像"}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
