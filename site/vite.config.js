// CardGap ダッシュボードサイトの Vite 設定。
// base: "./" にして、GitHub Pages のプロジェクトサイト
// (https://<user>.github.io/CardGap/ のようなサブパス配下)でも
// アセット参照が壊れないようにする。
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
});
