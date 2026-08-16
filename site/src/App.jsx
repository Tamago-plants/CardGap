// ルートコンポーネント。
// 起動時に ./data/*.json を3つ読み込み、各セクションへ配る。
// generated_at が null(バッチ未実行のプレースホルダ)のときは案内バナーを出す。
import { useEffect, useState } from "react";
import Header from "./components/Header.jsx";
import SummaryTiles from "./components/SummaryTiles.jsx";
import Movers from "./components/Movers.jsx";
import DealsTable from "./components/DealsTable.jsx";
import DealDetail from "./components/DealDetail.jsx";

// 相対パスで fetch する。base: "./" なので Pages のサブパス配下でも解決できる。
const DATA_FILES = ["./data/deals.json", "./data/history.json", "./data/summary.json"];

export default function App() {
  const [data, setData] = useState(null); // { deals, history, summary }
  const [error, setError] = useState(null);
  const [selectedDeal, setSelectedDeal] = useState(null);

  useEffect(() => {
    let cancelled = false;
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
  }, []);

  if (error) {
    return (
      <div className="container">
        <Header summary={null} />
        <div className="banner error">データの読み込みに失敗しました: {error}</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="container">
        <Header summary={null} />
        <p className="empty-note">読み込み中...</p>
      </div>
    );
  }

  const { deals, history, summary } = data;
  // どれか1つでも generated_at があれば「投入済み」とみなす
  const noData = !deals.generated_at && !history.generated_at && !summary.generated_at;

  // 選択中の案件に対応する価格履歴(card_id で引く)
  const historyCard = selectedDeal
    ? (history.cards || []).find((c) => c.card_id === selectedDeal.card_id) || null
    : null;

  return (
    <div className="container">
      <Header summary={summary} />

      {noData && (
        <div className="banner">
          データ未投入です。PC側で <code>python -m cardgap run</code>{" "}
          を実行して push してください。
        </div>
      )}

      <SummaryTiles summary={summary} hasData={!noData} />
      <Movers summary={summary} />
      <DealsTable
        deals={deals.deals || []}
        selectedDeal={selectedDeal}
        onSelect={(deal) =>
          setSelectedDeal((cur) => (cur && dealKey(cur) === dealKey(deal) ? null : deal))
        }
      />
      {selectedDeal && (
        <DealDetail
          deal={selectedDeal}
          historyCard={historyCard}
          onClose={() => setSelectedDeal(null)}
        />
      )}

      <footer className="site-footer">
        CardGap — トレカ相場乖離検出ツール(個人利用)
      </footer>
    </div>
  );
}

/** 案件の同一性判定キー(仕入元URL + カードID) */
function dealKey(deal) {
  return `${deal.card_id}::${deal.source}::${deal.listing_url}`;
}
