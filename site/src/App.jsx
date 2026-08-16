// ルートコンポーネント。
// 起動時に ./data/*.json を3つ読み込み、hashルーティングで4タブを切り替える。
// ドロワー(詳細)はどの画面からも開ける共通シェル要素としてここで管理する。
import { useCallback, useEffect, useMemo, useState } from "react";
import Header from "./components/Header.jsx";
import Dashboard from "./components/Dashboard.jsx";
import Rankings from "./components/Rankings.jsx";
import MarketMap from "./components/MarketMap.jsx";
import DealsScreen from "./components/DealsScreen.jsx";
import Drawer from "./components/Drawer.jsx";
import useHashState from "./hooks/useHashState.js";
import useTheme from "./hooks/useTheme.js";
import { buildSearchIndex, dealKey, historyByCard } from "./lib/data.js";
import { opportunityScore } from "./lib/score.js";

// 相対パスで fetch する。base: "./" なので Pages のサブパス配下でも解決できる。
const DATA_FILES = ["./data/deals.json", "./data/history.json", "./data/summary.json"];

export default function App() {
  const [data, setData] = useState(null); // { deals, history, summary }
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  // ドロワー選択: {cardId, dealKey|null}
  const [selection, setSelection] = useState(null);

  const { path, params, navigate, setParams } = useHashState();
  const { theme, toggle: toggleTheme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all(
      DATA_FILES.map((url) =>
        fetch(url).then((res) => {
          if (!res.ok) throw new Error(`${url} の取得に失敗しました (HTTP ${res.status})`);
          return res.json();
        })
      )
    )
      .then(([deals, history, summary]) => {
        if (!cancelled) setData({ deals, history, summary });
      })
      .catch((e) => {
        if (!cancelled) setError(String(e.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const deals = (data && data.deals && data.deals.deals) || [];
  const history = (data && data.history) || null;
  const summary = (data && data.summary) || null;

  const searchIndex = useMemo(
    () => buildSearchIndex(data && data.deals, history),
    [data, history]
  );
  const histMap = useMemo(() => historyByCard(history), [history]);
  const dealsByCard = useMemo(() => {
    const m = new Map();
    for (const d of deals) {
      const list = m.get(d.card_id) || [];
      list.push(d);
      m.set(d.card_id, list);
    }
    return m;
  }, [deals]);

  // どれか1つでも generated_at があれば「投入済み」とみなす
  const noData =
    !!data &&
    !(data.deals && data.deals.generated_at) &&
    !(history && history.generated_at) &&
    !(summary && summary.generated_at);

  const openDeal = useCallback((deal) => {
    setSelection({ cardId: deal.card_id, dealKey: dealKey(deal) });
  }, []);
  const openCard = useCallback((cardId) => {
    setSelection({ cardId, dealKey: null });
  }, []);
  const closeDrawer = useCallback(() => setSelection(null), []);

  // タブ移動したらドロワーは閉じる
  useEffect(() => {
    setSelection(null);
  }, [path]);

  // 選択からドロワー表示内容を解決(案件指定が無ければベストスコアの案件)
  const drawerData = useMemo(() => {
    if (!selection) return null;
    const cardDeals = dealsByCard.get(selection.cardId) || [];
    let deal = null;
    if (selection.dealKey) deal = cardDeals.find((d) => dealKey(d) === selection.dealKey) || null;
    if (!deal && cardDeals.length > 0) {
      deal = cardDeals.slice().sort((a, b) => opportunityScore(b) - opportunityScore(a))[0];
    }
    const histCard = histMap.get(selection.cardId) || null;
    const card = deal ||
      histCard || {
        card_id: selection.cardId,
        display_name: "不明なカード",
        category: null,
      };
    return { card, deal, cardDeals, histCard };
  }, [selection, dealsByCard, histMap]);

  return (
    <div className="app">
      <Header
        summary={summary}
        searchIndex={searchIndex}
        path={path}
        onNavigate={navigate}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenCard={openCard}
      />

      <main className="container">
        {error ? (
          <div className="banner error" role="alert">
            データの読み込みに失敗しました: {error}
            <div style={{ marginTop: 8 }}>
              <button type="button" className="btn btn-sm" onClick={() => setReloadKey((k) => k + 1)}>
                再読み込み
              </button>
            </div>
          </div>
        ) : !data ? (
          <p className="empty-note">読み込み中...</p>
        ) : (
          <>
            {noData && path !== "/dashboard" && (
              <div className="banner">
                データ未投入です。ダッシュボードのセットアップ手順を参照してください。
              </div>
            )}
            {path === "/dashboard" && (
              <Dashboard
                deals={deals}
                summary={summary}
                noData={noData}
                onOpenDeal={openDeal}
                onOpenCard={openCard}
              />
            )}
            {path === "/rankings" && (
              <Rankings
                deals={deals}
                history={history}
                params={params}
                setParams={setParams}
                onOpenDeal={openDeal}
                onOpenCard={openCard}
              />
            )}
            {path === "/market" && (
              <MarketMap
                deals={deals}
                history={history}
                theme={theme}
                params={params}
                setParams={setParams}
                onOpenCard={openCard}
              />
            )}
            {path === "/deals" && (
              <DealsScreen
                deals={deals}
                history={history}
                summary={summary}
                params={params}
                setParams={setParams}
                onOpenDeal={openDeal}
              />
            )}
          </>
        )}

        <footer className="site-footer">
          <span>
            相場はeBay Sold直近30日の中央値。検出は参考情報であり売買判断は自己責任でお願いします。
          </span>
          <a href="https://github.com/" target="_blank" rel="noopener noreferrer">
            GitHub
          </a>
        </footer>
      </main>

      {drawerData && (
        <Drawer
          card={drawerData.card}
          deal={drawerData.deal}
          cardDeals={drawerData.cardDeals}
          histCard={drawerData.histCard}
          summary={summary}
          onClose={closeDrawer}
          onSelectDeal={(d) => setSelection({ cardId: d.card_id, dealKey: dealKey(d) })}
        />
      )}
    </div>
  );
}
