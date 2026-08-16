// テーマ切替(初期値ダーク、localStorage に保存)。
// <html data-theme="light"> の有無で切り替える。トークンは styles.css 側で定義。

import { useCallback, useEffect, useState } from "react";

const KEY = "cardgap-theme";

export function applyStoredTheme() {
  // main.jsx から描画前に呼び、初回描画のフラッシュを防ぐ
  let t = "dark";
  try {
    t = localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    /* localStorage 不可でもダークで続行 */
  }
  document.documentElement.dataset.theme = t;
  return t;
}

export default function useTheme() {
  const [theme, setTheme] = useState(
    () => document.documentElement.dataset.theme || "dark"
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* 保存できなくても動作は継続 */
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggle };
}
