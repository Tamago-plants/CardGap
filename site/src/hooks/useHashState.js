// hash ルーティング + hashクエリの状態管理。
// "#/deals?f=above&src=mercari" を {path:"/deals", params:{f:"above",...}} として読む。
// setParams は history.replaceState で書き換え(戻るボタンを汚さない)、
// navigate はタブ移動用に通常の hash 変更(hashchange 発火)を使う。

import { useCallback, useEffect, useState } from "react";

const TABS = ["/dashboard", "/rankings", "/market", "/deals"];

function read() {
  const raw = window.location.hash.replace(/^#/, "");
  const [pathPart, queryPart] = raw.split("?");
  const path = TABS.includes(pathPart) ? pathPart : "/dashboard";
  const params = {};
  if (queryPart) {
    for (const [k, v] of new URLSearchParams(queryPart)) params[k] = v;
  }
  return { path, params };
}

function build(path, params) {
  const sp = new URLSearchParams();
  for (const k of Object.keys(params || {})) {
    const v = params[k];
    if (v != null && v !== "") sp.set(k, v);
  }
  const qs = sp.toString();
  return "#" + path + (qs ? "?" + qs : "");
}

// 複数コンポーネントで購読できるように listener を共有する
const listeners = new Set();

function broadcast() {
  const v = read();
  listeners.forEach((fn) => fn(v));
}

export default function useHashState() {
  const [state, setState] = useState(read);

  useEffect(() => {
    const onChange = () => broadcast();
    listeners.add(setState);
    window.addEventListener("hashchange", onChange);
    return () => {
      listeners.delete(setState);
      window.removeEventListener("hashchange", onChange);
    };
  }, []);

  const navigate = useCallback((path, params = {}) => {
    window.location.hash = build(path, params).slice(1);
  }, []);

  // フィルタ変更用: 現在のパスのまま、クエリだけ差分更新(nullで削除)
  const setParams = useCallback((patch) => {
    const cur = read();
    const next = { ...cur.params, ...patch };
    for (const k of Object.keys(next)) {
      if (next[k] == null || next[k] === "") delete next[k];
    }
    window.history.replaceState(null, "", build(cur.path, next));
    broadcast();
  }, []);

  return { path: state.path, params: state.params, navigate, setParams };
}
