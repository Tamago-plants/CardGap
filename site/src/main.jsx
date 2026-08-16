// エントリポイント。描画前にテーマを適用してから #root に App をマウントする。
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { applyStoredTheme } from "./hooks/useTheme.js";
import "./styles.css";

applyStoredTheme();

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
